"""Reusable authority tokens for a fixed synthetic receipt migration job."""
from __future__ import annotations

from pathlib import Path
import sqlite3

from src.compaction_store import intent_fingerprint
from src.selection_store import SelectionPublicationStore

MODES = ('cached_permission','separate_fence','transactional_fence')
MAX_INTEGER = 2**63-1


def positive(value):
    if type(value) is not int or not 1 <= value <= MAX_INTEGER:
        raise ValueError('positive SQLite-range integer required')


def pair(lease):
    return {key:lease[key] for key in ('owner','token')}


class ReclamationStore(SelectionPublicationStore):
    """One current slot, monotonic grants, trusted explicit replacement.

    Tokens fence stale holders; this is not a lifetime-work budget, an automatic
    failure detector, a clock-based lease or client authentication mechanism.
    """

    def __init__(self,root: Path,mode: str):
        if mode not in MODES:raise ValueError('unknown reclamation policy')
        super().__init__(root,'validated_selection')
        self.reclaim_mode=mode

    def initialize(self,content: bytes):
        super().initialize(content)
        connection=self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE reclaim_lease (id INTEGER PRIMARY KEY CHECK(id=1), policy TEXT NOT NULL, token INTEGER NOT NULL CHECK(token>0), owner INTEGER NOT NULL CHECK(owner>0))')
            connection.execute('INSERT INTO reclaim_lease VALUES (1,?,1,1)',(self.reclaim_mode,))
            connection.execute('CREATE TABLE token_grants (token INTEGER PRIMARY KEY, owner INTEGER NOT NULL, previous INTEGER NOT NULL)')
            connection.execute('INSERT INTO token_grants VALUES (1,1,0)')
            connection.execute('CREATE TABLE lease_effect (id INTEGER PRIMARY KEY CHECK(id=1), owner INTEGER NOT NULL, token INTEGER NOT NULL, current_owner INTEGER NOT NULL, current_token INTEGER NOT NULL, authorized INTEGER NOT NULL CHECK(authorized IN (0,1)))')
            connection.execute('COMMIT')
        finally:connection.close()

    def _lease(self,connection):
        row=connection.execute('SELECT policy,token,owner FROM reclaim_lease WHERE id=1').fetchone()
        if row is None or row[0]!=self.reclaim_mode:raise ValueError('fixed reclamation policy changed')
        return dict(zip(('policy','token','owner'),row))

    def _read_lease(self):
        connection=self._probe_connection()
        try:
            connection.execute('BEGIN')
            return self._lease(connection)
        finally:connection.close()

    def _read_selection(self,target):
        connection=self._probe_connection()
        try:
            connection.execute('BEGIN')
            self._lease(connection)
            return self._selection(connection,target)
        finally:connection.close()

    def replace(self,expected_token: int,owner: int):
        positive(expected_token);positive(owner)
        connection=self._probe_connection()
        try:
            try:connection.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as error:
                if getattr(error,'sqlite_errorcode',None)!=sqlite3.SQLITE_BUSY:raise
                return dict(status='busy',sqlite_errorcode=error.sqlite_errorcode)
            current=self._lease(connection)
            if self._active_epoch(connection)==2:return dict(status='completed',active_epoch=2)
            if current['token']!=expected_token:return dict(status='conflict',lease=pair(current))
            if expected_token==MAX_INTEGER:raise ValueError('token space exhausted')
            token=expected_token+1
            connection.execute('UPDATE reclaim_lease SET owner=?,token=? WHERE id=1',(owner,token))
            connection.execute('INSERT INTO token_grants VALUES (?,?,?)',(token,owner,expected_token))
            connection.execute('COMMIT')
            return dict(status='reclaimed',lease=dict(owner=owner,token=token),previous=expected_token)
        finally:connection.close()

    def migrate_once(self,lease,*,checkpoint=lambda stage:None,event=lambda kind,**fields:None):
        if not isinstance(lease,dict) or set(lease)!= {'owner','token'}:raise ValueError('exact owner/token pair required')
        positive(lease['owner']);positive(lease['token'])
        checkpoint('before_selection')
        selected=self._read_selection(2)
        event('source_selected',**self.describe(selected))
        if selected['active_epoch']==2:return dict(status='completed',active_epoch=2)
        if selected['active_epoch']!=1:raise ValueError('unexpected target namespace')
        checkpoint('after_selection')
        if self.reclaim_mode=='separate_fence':
            observed=pair(self._read_lease());valid=observed==lease
            event('fence_checked',scope='separate',lease=observed,valid=valid)
            if not valid:return dict(status='stale_lease',active_epoch=1)
            checkpoint('after_fence')
        elif self.reclaim_mode=='cached_permission':
            event('fence_cached',lease=lease)
            checkpoint('after_fence')
        connection=self._probe_connection()
        try:
            try:connection.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as error:
                if getattr(error,'sqlite_errorcode',None)!=sqlite3.SQLITE_BUSY:raise
                event('writer_busy',sqlite_errorcode=error.sqlite_errorcode)
                return dict(status='busy',sqlite_errorcode=error.sqlite_errorcode)
            current=pair(self._lease(connection));observed=self._selection(connection,2)
            event('writer_view',lease=current,active_epoch=observed['active_epoch'])
            if observed['active_epoch']==2:return dict(status='completed',active_epoch=2)
            valid=current==lease
            if self.reclaim_mode=='transactional_fence':
                event('fence_checked',scope='transaction',lease=current,valid=valid)
                if not valid:return dict(status='stale_lease',active_epoch=1)
                checkpoint('after_fence')
            matched=selected==observed
            event('source_validation',matched=matched,observed=self.describe(observed))
            if not matched:return dict(status='stale_source',active_epoch=observed['active_epoch'])
            connection.execute('UPDATE namespace SET active_epoch=2 WHERE id=1')
            connection.execute('DELETE FROM requests WHERE epoch<2')
            compact=[(epoch,key,op,intent_fingerprint(payload),revision) for epoch,key,op,payload,revision,approved in selected['rows']]
            connection.executemany('INSERT INTO summaries VALUES (?,?,?,?,?)',compact)
            connection.execute('INSERT INTO migration_witness VALUES (1,2,?,?,?,?)',(selected['current_revision'],observed['current_revision'],len(compact),len(observed['rows'])))
            witness=dict(owner=lease['owner'],token=lease['token'],current_owner=current['owner'],current_token=current['token'],authorized=valid)
            connection.execute('INSERT INTO lease_effect VALUES (1,?,?,?,?,?)',tuple(witness.values()))
            event('effect_prepared',**witness)
            checkpoint('before_commit')
            connection.execute('COMMIT')
            event('effect_committed',**witness)
            checkpoint('after_commit')
            return dict(status='migrated',active_epoch=2,**lease)
        finally:connection.close()

    def inspect(self):
        # Application and observer state share this one read snapshot.
        connection=self._connect()
        try:
            connection.execute('BEGIN')
            result=dict(state=self._row(connection),active_epoch=self._active_epoch(connection))
            tables=(('effects',('revision','epoch','request_id','operation','approved_sha256'),'revision'),
                    ('requests',('epoch','request_id','operation','payload','revision','approved_sha256'),'epoch,request_id'),
                    ('summaries',('epoch','request_id','operation','payload_sha256','revision'),'epoch,request_id'),
                    ('publication_witnesses',('revision','requested_epoch','active_epoch','request_id'),'revision'),
                    ('token_grants',('token','owner','previous'),'token'))
            for table,columns,order in tables:
                rows=connection.execute('SELECT '+','.join(columns)+' FROM '+table+' ORDER BY '+order)
                result['receipts' if table=='requests' else 'grants' if table=='token_grants' else table]=[dict(zip(columns,row)) for row in rows]
            columns=('target_epoch','selected_revision','write_revision','selected_count','write_count')
            row=connection.execute('SELECT '+','.join(columns)+' FROM migration_witness WHERE id=1').fetchone()
            result['migration_witness']=None if row is None else dict(zip(columns,row))
            columns=('owner','token','current_owner','current_token','authorized')
            row=connection.execute('SELECT '+','.join(columns)+' FROM lease_effect WHERE id=1').fetchone()
            result['lease_effect']=None if row is None else dict(zip(columns,row))
            if row is not None:result['lease_effect']['authorized']=bool(row[-1])
            result['lease']=self._lease(connection)
            result['summary_columns']=[r[1] for r in connection.execute('PRAGMA table_info(summaries)')]
            connection.execute('COMMIT')
            return result
        finally:connection.close()
