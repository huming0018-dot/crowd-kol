"""Durable machine workflow observations. No request, credential or raw error fields."""
import json
import re
import sqlite3
import time
import threading
import uuid

PHASES = frozenset(('claiming','authorized','dispatching','running','importing','delivering','finishing','waiting_login','login_resumed','paused','completed','deferring_delivery','reconciling_no_dispatch','local_stop_unknown','comments_page','source_step'))

class MachineSteps:
    def __init__(self, path, client):
        self.path, self.client, self.error = path, client, None
        self.closed=threading.Event()
        self.thread=None
        self.disabled=False
        if path.is_symlink():
            self.disabled=True
            self.error='machine_steps_store_failed'
            return
        try:
            with self.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS steps(id TEXT PRIMARY KEY,run TEXT NOT NULL,epoch INTEGER NOT NULL,event TEXT NOT NULL,observed_at_ms INTEGER NOT NULL,ack INTEGER NOT NULL DEFAULT 0,error TEXT)')
            path.chmod(0o600)
        except (sqlite3.Error,OSError):
            self.disabled=True
            self.error='machine_steps_store_failed'

    def connect(self):
        if self.disabled or self.path.is_symlink():raise ValueError('unsafe_machine_steps')
        return sqlite3.connect(self.path, timeout=5)

    def observe(self, state, phase=None, **counts):
        lease = state.get('lease') or {}
        phase = phase or state.get('phase')
        if not lease or phase not in PHASES:
            return
        run = str(uuid.UUID(lease['run_id']))
        epoch = lease['lease_epoch']
        if type(epoch) is not int or epoch < 1:
            raise ValueError('invalid_machine_steps')
        event = {'phase':phase}
        if state.get('outcome') in ('completed','failed','stopped','unknown','login_required'):
            event['outcome']=state['outcome']
        if state.get('local_run_id'):
            event['local_run_id'] = str(uuid.UUID(state['local_run_id']))
        for key in ('saved_pages','saved_rows','acknowledged','pending','page_index'):
            value = counts.get(key)
            if value is not None:
                if type(value) is not int or not 0 <= value <= 10**9:
                    raise ValueError('invalid_machine_steps')
                event[key] = value
        if phase!='source_step' and any(key in counts for key in ('source_sequence','source_stage','api_attempts','http_status')):raise ValueError('invalid_machine_steps')
        if phase not in ('source_step','comments_page') and 'scope' in counts:raise ValueError('invalid_machine_steps')
        if phase=='source_step':
            from mc_source_steps import STAGES,SCOPES
            if counts.get('source_stage') not in STAGES or counts.get('scope') not in SCOPES:raise ValueError('invalid_machine_steps')
            if counts['source_stage']=='page_partially_saved' and (counts['scope'] not in ('root','reply') or type(counts.get('saved_rows')) is not int or counts['saved_rows']<1):raise ValueError('invalid_machine_steps')
            for key,low,high in (('source_sequence',1,4000),('api_attempts',0,500),('http_status',0,599)):
                value=counts.get(key)
                if type(value) is not int or not low<=value<=high:raise ValueError('invalid_machine_steps')
                event[key]=value
            if counts.get('checkpoint_committed') is not False:raise ValueError('invalid_machine_steps')
            event.update(source_stage=counts['source_stage'],scope=counts['scope'],checkpoint_committed=False)
            if 'page_sha256' in counts:
                if not isinstance(counts['page_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',counts['page_sha256']):raise ValueError('invalid_machine_steps')
                event['page_sha256']=counts['page_sha256']
        if phase=='comments_page':
            scope=counts.get('scope')
            if scope not in ('root','reply') or type(counts.get('checkpoint_committed')) is not bool:
                raise ValueError('invalid_machine_steps')
            digest=counts.get('page_sha256')
            if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('invalid_machine_steps')
            event.update(scope=scope,checkpoint_committed=counts['checkpoint_committed'],page_sha256=digest)
        encoded = json.dumps(event, sort_keys=True, separators=(',',':'))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute("SELECT event FROM steps WHERE run=? AND epoch=? AND json_extract(event,'$.phase') NOT IN ('comments_page','source_step') ORDER BY rowid DESC LIMIT 1",(run,epoch)).fetchone()
            if phase not in ('comments_page','source_step') and previous and previous[0] == encoded:
                return
            identity=str(uuid.uuid5(uuid.UUID(run),str(epoch)+'\n'+encoded)) if phase in ('comments_page','source_step') else str(uuid.uuid4())
            db.execute('INSERT OR IGNORE INTO steps(id,run,epoch,event,observed_at_ms) VALUES(?,?,?,?,?)',(identity,run,epoch,encoded,int(time.time()*1000)))

    def flush(self):
        try:
            with self.connect() as db:
                rows = db.execute('SELECT rowid,id,run,epoch,event,observed_at_ms FROM steps WHERE ack=0 AND error IS NULL ORDER BY rowid LIMIT 1').fetchall()
            if not rows:
                self.error = None
                return
            with self.connect() as db:
                rows=db.execute('SELECT rowid,id,run,epoch,event,observed_at_ms FROM steps WHERE ack=0 AND error IS NULL AND run=? AND epoch=? ORDER BY rowid LIMIT 50',(rows[0][2],rows[0][3])).fetchall()
            events = [{'sequence':sequence,'event_id':identity,'run_id':run,'lease_epoch':epoch,'observed_at_ms':observed,**json.loads(event)} for sequence,identity,run,epoch,event,observed in rows]
            response = self.client.call('step_events', {'events':events})
            expected = [row[1] for row in rows]
            if response.get('event_ids') != expected:
                raise ValueError('machine_steps_ack_mismatch')
            with self.connect() as db:
                db.executemany('UPDATE steps SET ack=1 WHERE id=?',[(identity,) for identity in expected])
            self.error = None
        except Exception as error:
            if str(error) in ('lease_binding_denied','worker_revoked','step_event_conflict','invalid_step_events') and 'rows' in locals():
                try:
                    with self.connect() as db:
                        db.executemany('UPDATE steps SET error=? WHERE id=?',[(str(error),row[1]) for row in rows])
                except sqlite3.Error:
                    pass
            # Telemetry transport must not restart a source or suppress delivery.
            self.error = 'machine_steps_delivery_failed'

    def status(self):
        try:
            with self.connect() as db:
                pending = db.execute('SELECT count(*) FROM steps WHERE ack=0').fetchone()[0]
                blocked = db.execute('SELECT count(*) FROM steps WHERE ack=0 AND error IS NOT NULL').fetchone()[0]
            return {'pending':pending,'blocked':blocked,'error':self.error}
        except (ValueError,sqlite3.Error,OSError):
            return {'pending':None,'blocked':None,'error':'machine_steps_store_failed'}

    def start(self):
        if self.disabled or self.thread is not None:return
        def loop():
            while not self.closed.is_set():
                self.flush()
                self.closed.wait(10 if self.error else 2)
        self.thread=threading.Thread(target=loop,daemon=True,name='cloud-machine-steps')
        self.thread.start()

    def close(self):
        self.closed.set()
        if self.thread:self.thread.join(timeout=1)
