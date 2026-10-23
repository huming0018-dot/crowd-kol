"""Worker-only POSIX node, using the unchanged normal task/session/receipt chain.

The operator supplies a separately paired worker-key config and an existing
legally installed collector/session. Never supply an Owner key or copy another
node's account/profile/state. Windows hosts use a separately installed WSL2
Linux distribution; this is not a native Windows runtime.
"""
from pathlib import Path
import argparse,json,os,signal,threading
from dashboard import Application
from cloud_sync import CloudClient,CloudWorker

class MachineNode(Application):
    def __init__(self,root,mc_root,collector_roots,*,client=None,runner=None):
        if os.name!='posix':raise ValueError('linux_or_macos_required')
        self.root=Path(root).expanduser().absolute()
        if self.root.resolve()!=self.root:raise ValueError('unsafe_node_root')
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.root.stat().st_mode&0o077:raise ValueError('node_root_requires_0700')
        self.mc_root=str(Path(mc_root).expanduser().resolve())
        if not Path(self.mc_root).is_dir():raise ValueError('collector_installation_required')
        self.collector_roots=list(dict.fromkeys(Path(p).expanduser().resolve()for p in collector_roots))
        for p in self.collector_roots:
            if not p.is_dir()or not(p/'runs').is_dir()or not(p/'sessions').is_dir():raise ValueError('collector_root_required')
        if not self.collector_roots:raise ValueError('collector_root_required')
        self.runner_root=self.root/'collector';self.config_path=self.root/'dashboard-config.json'
        self.preferred_session_by_platform={};self.lock=threading.Lock()
        self.results_store=None;self.automatic_materials=None;self.light_transcripts=None
        # Explicit minimal Application task context: no OwnerAdapter, watchlists,
        # HTTP server, scheduler construction, account registration or Owner key.
        self.cloud_client=client if client is not None else CloudClient(self.root/'cloud-config.json','worker')
        if client is None and 'owner_key'in self.cloud_client.config:raise ValueError('worker_only_config_required')
        self.cloud_worker=CloudWorker(self.root,self.cloud_client,runner if runner is not None else self.task_run,
             self._cloud_session,self._cloud_existing,capability_provider=lambda:[],readiness_provider=self._source_readiness)
    def serve(self):
        closed=threading.Event();previous={}
        def stop(*_):closed.set()
        for signum in (signal.SIGTERM,signal.SIGINT):previous[signum]=signal.signal(signum,stop)
        try:
            self.cloud_worker.start_scheduler()
            print(json.dumps({'state':'worker_started','role':'worker'}),flush=True)
            closed.wait()
        finally:
            # Original durable inflight/outbox state remains resumable. This does
            # not silently Stop a source, clear unknown, or synthesize a finish.
            self.cloud_worker.close()
            for signum,handler in previous.items():signal.signal(signum,handler)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--mc-root',type=Path,required=True)
    parser.add_argument('--collector-root',type=Path,action='append',required=True)
    parser.add_argument('--check',action='store_true',help='Local dependency/identity preflight only; no cloud RPC or scheduler')
    args=parser.parse_args();node=MachineNode(args.root,args.mc_root,args.collector_root)
    if args.check:
        try:
            value=node._source_readiness();print(json.dumps({'state':value['state'],'reason_code':value['reason_code'],'host':value['host']}))
            return 0 if value['state']=='ready'else 2
        finally:node.cloud_worker.close()
    node.serve();return 0
if __name__=='__main__':raise SystemExit(main())
