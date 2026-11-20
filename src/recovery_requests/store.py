"""Request-bound historical recovery results over reusable authority tokens."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from src.reclamation.store import MAX_INTEGER,ReclamationStore,pair,positive

MODES=('current_only','separate_receipt','atomic_receipt')


def validate_request(request):
    if not isinstance(request,dict) or set(request)!={'request_id','expected_token','owner'}:
        raise ValueError('exact request ID, expected token and owner required')
    key=request['request_id']
    if type(key) is not str or not 1<=len(key)<=128 or any(ord(c)<32 or ord(c)==127 for c in key):
        raise ValueError('nonempty request ID without control characters required')
    try:key.encode('utf-8')
    except UnicodeEncodeError as error:raise ValueError('UTF-8 request ID required') from error
    positive(request['expected_token']);positive(request['owner'])


def encode(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def response(status,request,outcome=None):
    result=dict(status=status,request_id=request['request_id'])
    if outcome is not None:result['outcome']=outcome
    return result


class RecoveryRequestStore(ReclamationStore):
    def __init__(self,root: Path,mode: str):
        if mode not in MODES:raise ValueError('unknown recovery request policy')
        super().__init__(root,'transactional_fence');self.request_mode=mode

    def initialize(self,content: bytes):
        super().initialize(content);connection=self._connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE recovery_policy (id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL)')
            connection.execute('INSERT INTO recovery_policy VALUES (1,?)',(self.request_mode,))
            connection.execute('CREATE TABLE recovery_receipts (request_id TEXT PRIMARY KEY, expected_token INTEGER NOT NULL, owner INTEGER NOT NULL, outcome_json TEXT NOT NULL)')
            connection.execute('CREATE TABLE decision_witnesses (ordinal INTEGER PRIMARY KEY, request_id TEXT NOT NULL, expected_token INTEGER NOT NULL, owner INTEGER NOT NULL, outcome_json TEXT NOT NULL, effect_token INTEGER)')
            connection.execute('COMMIT')
        finally:connection.close()

    def _policy(self,connection):
        row=connection.execute('SELECT mode FROM recovery_policy WHERE id=1').fetchone()
        if row!=(self.request_mode,):raise ValueError('fixed request policy changed')
        return row[0]

    def _lookup(self,connection,key):
        row=connection.execute('SELECT expected_token,owner,outcome_json FROM recovery_receipts WHERE request_id=?',(key,)).fetchone()
        return None if row is None else dict(request_id=key,expected_token=row[0],owner=row[1],outcome=json.loads(row[2]))

    @staticmethod
    def _from_receipt(request,receipt):
        if any(request[k]!=receipt[k] for k in ('request_id','expected_token','owner')):
            return response('request_conflict',request)
        return response('replayed',request,receipt['outcome'])

    def _begin(self,connection,request,event,at):
        try:connection.execute('BEGIN IMMEDIATE');return None
        except sqlite3.OperationalError as error:
            if getattr(error,'sqlite_errorcode',None)!=sqlite3.SQLITE_BUSY:raise
            event('writer_busy',at=at,sqlite_errorcode=error.sqlite_errorcode)
            return dict(status='busy',request_id=request['request_id'],sqlite_errorcode=error.sqlite_errorcode)

    def _decide(self,connection,request):
        current=self._lease(connection);epoch=self._active_epoch(connection)
        if epoch==2:return dict(status='completed',active_epoch=2),None
        expected=request['expected_token']
        if current['token']!=expected:return dict(status='conflict',lease=pair(current)),None
        if expected==MAX_INTEGER:raise ValueError('token space exhausted')
        token=expected+1;owner=request['owner']
        connection.execute('UPDATE reclaim_lease SET owner=?,token=? WHERE id=1',(owner,token))
        connection.execute('INSERT INTO token_grants VALUES (?,?,?)',(token,owner,expected))
        return dict(status='reclaimed',lease=dict(owner=owner,token=token),previous=expected),token

    def _save_receipt(self,connection,request,outcome):
        connection.execute('INSERT INTO recovery_receipts VALUES (?,?,?,?)',(request['request_id'],request['expected_token'],request['owner'],encode(outcome)))
        return {**request,'outcome':outcome}

    def replace_once(self,request,*,checkpoint=lambda stage:None,event=lambda kind,**fields:None):
        request=dict(request) if isinstance(request,dict) else request
        validate_request(request)
        def finish(answer):checkpoint('before_reply');return answer
        if self.request_mode=='separate_receipt':
            connection=self._probe_connection()
            try:
                connection.execute('BEGIN');self._policy(connection)
                receipt=self._lookup(connection,request['request_id'])
            finally:connection.close()
            event('receipt_lookup',scope='separate',receipt=receipt)
            checkpoint('after_lookup')
            if receipt is not None:return finish(self._from_receipt(request,receipt))
        elif self.request_mode=='current_only':
            event('receipt_lookup',scope='none',receipt=None)
            checkpoint('after_lookup')
        connection=self._probe_connection()
        try:
            busy=self._begin(connection,request,event,'decision')
            if busy is not None:return finish(busy)
            self._policy(connection)
            if self.request_mode=='atomic_receipt':
                receipt=self._lookup(connection,request['request_id'])
                event('receipt_lookup',scope='transaction',receipt=receipt)
                checkpoint('after_lookup')
                if receipt is not None:
                    connection.execute('ROLLBACK')
                    return finish(self._from_receipt(request,receipt))
            outcome,effect_token=self._decide(connection,request)
            cursor=connection.execute('INSERT INTO decision_witnesses (request_id,expected_token,owner,outcome_json,effect_token) VALUES (?,?,?,?,?)',
                                      (request['request_id'],request['expected_token'],request['owner'],encode(outcome),effect_token))
            witness=dict(ordinal=cursor.lastrowid,**request,outcome=outcome,effect_token=effect_token)
            event('decision_prepared',**witness)
            if self.request_mode=='atomic_receipt':event('receipt_prepared',receipt=self._save_receipt(connection,request,outcome))
            checkpoint('before_decision_commit')
            connection.execute('COMMIT')
            event('decision_committed',**witness)
            checkpoint('after_decision_commit')
        finally:connection.close()
        if self.request_mode=='separate_receipt':
            connection=self._probe_connection()
            try:
                busy=self._begin(connection,request,event,'receipt')
                if busy is not None:return finish(busy)
                self._policy(connection);receipt=self._lookup(connection,request['request_id'])
                event('receipt_resolution',receipt=receipt)
                if receipt is not None:
                    connection.execute('ROLLBACK')
                    return finish(self._from_receipt(request,receipt))
                receipt=self._save_receipt(connection,request,outcome)
                connection.execute('COMMIT');event('receipt_committed',receipt=receipt)
            finally:connection.close()
            return finish(response('recorded',request,outcome))
        return finish(response('recorded' if self.request_mode=='atomic_receipt' else 'observed',request,outcome))

    def inspect(self):
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
                name='receipts' if table=='requests' else 'grants' if table=='token_grants' else table
                result[name]=[dict(zip(columns,row)) for row in rows]
            columns=('target_epoch','selected_revision','write_revision','selected_count','write_count')
            row=connection.execute('SELECT '+','.join(columns)+' FROM migration_witness WHERE id=1').fetchone()
            result['migration_witness']=None if row is None else dict(zip(columns,row))
            columns=('owner','token','current_owner','current_token','authorized')
            row=connection.execute('SELECT '+','.join(columns)+' FROM lease_effect WHERE id=1').fetchone()
            result['lease_effect']=None if row is None else dict(zip(columns,row))
            if row is not None:result['lease_effect']['authorized']=bool(row[-1])
            result['lease']=self._lease(connection);result['request_mode']=self._policy(connection)
            result['summary_columns']=[r[1] for r in connection.execute('PRAGMA table_info(summaries)')]
            result['recovery_receipts']=[dict(request_id=r[0],expected_token=r[1],owner=r[2],outcome=json.loads(r[3])) for r in connection.execute('SELECT request_id,expected_token,owner,outcome_json FROM recovery_receipts ORDER BY request_id')]
            result['decisions']=[dict(ordinal=r[0],request_id=r[1],expected_token=r[2],owner=r[3],outcome=json.loads(r[4]),effect_token=r[5]) for r in connection.execute('SELECT ordinal,request_id,expected_token,owner,outcome_json,effect_token FROM decision_witnesses ORDER BY ordinal')]
            connection.execute('COMMIT');return result
        finally:connection.close()
