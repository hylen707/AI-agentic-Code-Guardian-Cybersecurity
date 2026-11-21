"""Bounded namespaced recovery results and transactional epoch retirement."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from src.reclamation.store import MAX_INTEGER, ReclamationStore, positive
from src.recovery_requests.store import RecoveryRequestStore, encode, validate_request as validate_base

MODES = ('erase_only', 'cached_floor', 'atomic_floor')
CAPACITY = 2


def validate_request(request):
    if not isinstance(request, dict) or set(request) != {'recovery_epoch', 'request_id', 'expected_token', 'owner'}:
        raise ValueError('exact recovery epoch, ID, expected token and owner required')
    positive(request['recovery_epoch'])
    validate_base({key: value for key, value in request.items() if key != 'recovery_epoch'})


def validate_advance(request):
    if not isinstance(request, dict) or set(request) != {'expected_epoch'}:
        raise ValueError('exact expected recovery epoch required')
    positive(request['expected_epoch'])


def reply(status, request, **fields):
    return dict(status=status, recovery_epoch=request['recovery_epoch'], request_id=request['request_id'], **fields)


class RecoveryRetentionStore(ReclamationStore):
    def __init__(self, root: Path, mode: str):
        if mode not in MODES:
            raise ValueError('unknown retention policy')
        super().__init__(root, 'transactional_fence')
        self.retention_mode = mode

    def initialize(self, content: bytes):
        super().initialize(content)
        connection = self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE retention_policy (id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL, capacity INTEGER NOT NULL, active_recovery_epoch INTEGER NOT NULL CHECK(active_recovery_epoch>0))')
            connection.execute('INSERT INTO retention_policy VALUES (1,?,?,1)', (self.retention_mode, CAPACITY))
            connection.execute('CREATE TABLE retained_results (recovery_epoch INTEGER NOT NULL, request_id TEXT NOT NULL, expected_token INTEGER NOT NULL, owner INTEGER NOT NULL, outcome_json TEXT NOT NULL, PRIMARY KEY(recovery_epoch,request_id))')
            connection.execute('CREATE TABLE retention_decisions (ordinal INTEGER PRIMARY KEY, recovery_epoch INTEGER NOT NULL, request_id TEXT NOT NULL, expected_token INTEGER NOT NULL, owner INTEGER NOT NULL, outcome_json TEXT NOT NULL, effect_token INTEGER, active_recovery_epoch INTEGER NOT NULL)')
            connection.execute('CREATE TABLE retirement_witnesses (ordinal INTEGER PRIMARY KEY, from_epoch INTEGER NOT NULL, to_epoch INTEGER NOT NULL, removed_receipts INTEGER NOT NULL)')
            connection.execute('COMMIT')
        finally:
            connection.close()

    def _policy(self, connection):
        row = connection.execute('SELECT mode,capacity,active_recovery_epoch FROM retention_policy WHERE id=1').fetchone()
        if row is None or row[:2] != (self.retention_mode, CAPACITY):
            raise ValueError('fixed retention policy changed')
        positive(row[2])
        return row[2]

    def _begin(self, connection, role, request, event):
        try:
            connection.execute('BEGIN IMMEDIATE')
            return None
        except sqlite3.OperationalError as error:
            if getattr(error, 'sqlite_errorcode', None) != sqlite3.SQLITE_BUSY:
                raise
            event('writer_busy', role=role, sqlite_errorcode=error.sqlite_errorcode)
            return reply('busy', request, sqlite_errorcode=5) if role == 'replace' else dict(status='busy', sqlite_errorcode=5)

    def _admit(self, connection, request, event, scope):
        current = self._policy(connection)
        epoch = request['recovery_epoch']
        fate = 'future_epoch' if epoch > current else 'retired' if epoch < current and self.retention_mode != 'erase_only' else 'accepted'
        event('admission_checked', scope=scope, active_recovery_epoch=current, fate=fate)
        return None if fate == 'accepted' else reply(fate, request, active_recovery_epoch=current)

    def _lookup(self, connection, request):
        row = connection.execute('SELECT expected_token,owner,outcome_json FROM retained_results WHERE recovery_epoch=? AND request_id=?', (request['recovery_epoch'], request['request_id'])).fetchone()
        return None if row is None else dict(recovery_epoch=request['recovery_epoch'], request_id=request['request_id'], expected_token=row[0], owner=row[1], outcome=json.loads(row[2]))

    # The unchanged Phase 20 decision operates only on current authority/target.
    _decide = RecoveryRequestStore._decide

    def replace_once(self, request, *, checkpoint=lambda stage: None, event=lambda kind, **fields: None):
        request = dict(request) if isinstance(request, dict) else request
        validate_request(request)
        def finish(answer):
            checkpoint('before_reply')
            return answer
        if self.retention_mode != 'atomic_floor':
            connection = self._probe_connection()
            try:
                connection.execute('BEGIN')
                denied = self._admit(connection, request, event, 'separate')
            finally:
                connection.close()
            checkpoint('after_admission')
            if denied is not None:
                return finish(denied)
        connection = self._probe_connection()
        try:
            busy = self._begin(connection, 'replace', request, event)
            if busy is not None:
                return finish(busy)
            current = self._policy(connection)
            if self.retention_mode == 'atomic_floor':
                denied = self._admit(connection, request, event, 'transaction')
                checkpoint('after_admission')
                if denied is not None:
                    connection.execute('ROLLBACK')
                    return finish(denied)
            receipt = self._lookup(connection, request)
            event('receipt_lookup', receipt=receipt)
            checkpoint('after_lookup')
            if receipt is not None:
                connection.execute('ROLLBACK')
                if any(request[key] != receipt[key] for key in request):
                    return finish(reply('request_conflict', request))
                return finish(reply('replayed', request, outcome=receipt['outcome']))
            count = connection.execute('SELECT count(*) FROM retained_results WHERE recovery_epoch=?', (request['recovery_epoch'],)).fetchone()[0]
            event('capacity_checked', count=count, capacity=CAPACITY)
            if count >= CAPACITY:
                connection.execute('ROLLBACK')
                return finish(reply('capacity_exhausted', request, capacity=CAPACITY))
            outcome, token = self._decide(connection, request)
            cursor = connection.execute('INSERT INTO retention_decisions (recovery_epoch,request_id,expected_token,owner,outcome_json,effect_token,active_recovery_epoch) VALUES (?,?,?,?,?,?,?)',
                                        (request['recovery_epoch'], request['request_id'], request['expected_token'], request['owner'], encode(outcome), token, current))
            witness = dict(ordinal=cursor.lastrowid, **request, outcome=outcome, effect_token=token, active_recovery_epoch=current)
            event('decision_prepared', **witness)
            receipt = dict(**request, outcome=outcome)
            connection.execute('INSERT INTO retained_results VALUES (?,?,?,?,?)', (request['recovery_epoch'], request['request_id'], request['expected_token'], request['owner'], encode(outcome)))
            event('receipt_prepared', receipt=receipt)
            checkpoint('before_decision_commit')
            connection.execute('COMMIT')
            event('decision_committed', **witness)
            checkpoint('after_decision_commit')
        finally:
            connection.close()
        return finish(reply('recorded', request, outcome=outcome))

    def advance_epoch(self, request, *, checkpoint=lambda stage: None, event=lambda kind, **fields: None):
        request = dict(request) if isinstance(request, dict) else request
        validate_advance(request)
        def finish(answer):
            checkpoint('before_reply')
            return answer
        connection = self._probe_connection()
        try:
            busy = self._begin(connection, 'advance', request, event)
            if busy is not None:
                return finish(busy)
            current = self._policy(connection)
            event('rotation_view', active_recovery_epoch=current)
            if current != request['expected_epoch']:
                connection.execute('ROLLBACK')
                return finish(dict(status='epoch_conflict', active_recovery_epoch=current))
            if current == MAX_INTEGER:
                raise ValueError('recovery epoch space exhausted')
            removed = connection.execute('DELETE FROM retained_results WHERE recovery_epoch<?', (current + 1,)).rowcount
            connection.execute('UPDATE retention_policy SET active_recovery_epoch=? WHERE id=1', (current + 1,))
            cursor = connection.execute('INSERT INTO retirement_witnesses (from_epoch,to_epoch,removed_receipts) VALUES (?,?,?)', (current, current + 1, removed))
            witness = dict(ordinal=cursor.lastrowid, from_epoch=current, to_epoch=current + 1, removed_receipts=removed)
            event('rotation_prepared', **witness)
            checkpoint('before_rotation_commit')
            connection.execute('COMMIT')
            event('rotation_committed', **witness)
            checkpoint('after_rotation_commit')
        finally:
            connection.close()
        return finish(dict(status='advanced', previous_epoch=current, active_recovery_epoch=current + 1, removed_receipts=removed))

    def inspect(self):
        connection = self._connect()
        try:
            connection.execute('BEGIN')
            result = dict(state=self._row(connection), active_epoch=self._active_epoch(connection))
            tables = (('effects', ('revision', 'epoch', 'request_id', 'operation', 'approved_sha256'), 'revision'),
                      ('requests', ('epoch', 'request_id', 'operation', 'payload', 'revision', 'approved_sha256'), 'epoch,request_id'),
                      ('summaries', ('epoch', 'request_id', 'operation', 'payload_sha256', 'revision'), 'epoch,request_id'),
                      ('publication_witnesses', ('revision', 'requested_epoch', 'active_epoch', 'request_id'), 'revision'),
                      ('token_grants', ('token', 'owner', 'previous'), 'token'))
            for table, columns, order in tables:
                rows = connection.execute('SELECT ' + ','.join(columns) + ' FROM ' + table + ' ORDER BY ' + order)
                name = 'receipts' if table == 'requests' else 'grants' if table == 'token_grants' else table
                result[name] = [dict(zip(columns, row)) for row in rows]
            columns = ('target_epoch', 'selected_revision', 'write_revision', 'selected_count', 'write_count')
            row = connection.execute('SELECT ' + ','.join(columns) + ' FROM migration_witness WHERE id=1').fetchone()
            result['migration_witness'] = None if row is None else dict(zip(columns, row))
            columns = ('owner', 'token', 'current_owner', 'current_token', 'authorized')
            row = connection.execute('SELECT ' + ','.join(columns) + ' FROM lease_effect WHERE id=1').fetchone()
            result['lease_effect'] = None if row is None else dict(zip(columns, row))
            if row is not None:
                result['lease_effect']['authorized'] = bool(row[-1])
            result['lease'] = self._lease(connection)
            result['summary_columns'] = [r[1] for r in connection.execute('PRAGMA table_info(summaries)')]
            result.update(retention_mode=self.retention_mode, capacity=CAPACITY, active_recovery_epoch=self._policy(connection))
            result['retained_results'] = [dict(recovery_epoch=r[0], request_id=r[1], expected_token=r[2], owner=r[3], outcome=json.loads(r[4])) for r in connection.execute('SELECT recovery_epoch,request_id,expected_token,owner,outcome_json FROM retained_results ORDER BY recovery_epoch,request_id')]
            result['decisions'] = [dict(ordinal=r[0], recovery_epoch=r[1], request_id=r[2], expected_token=r[3], owner=r[4], outcome=json.loads(r[5]), effect_token=r[6], active_recovery_epoch=r[7]) for r in connection.execute('SELECT ordinal,recovery_epoch,request_id,expected_token,owner,outcome_json,effect_token,active_recovery_epoch FROM retention_decisions ORDER BY ordinal')]
            result['retirements'] = [dict(ordinal=r[0], from_epoch=r[1], to_epoch=r[2], removed_receipts=r[3]) for r in connection.execute('SELECT ordinal,from_epoch,to_epoch,removed_receipts FROM retirement_witnesses ORDER BY ordinal')]
            connection.execute('COMMIT')
            return result
        finally:
            connection.close()
