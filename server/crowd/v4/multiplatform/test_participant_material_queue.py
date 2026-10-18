import copy,json,tempfile,unittest
from pathlib import Path
from cloud_sync import CloudWorker

class QueueTests(unittest.TestCase):
    def test_feed_is_durable_and_reuses_postprocessing_retry(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); events=[]; ready=False
            from automatic_materials import material_context_key
            context={'schema':'crowd-participant-pro-material-context-v1','task_id':29,
                     'subject':'00000000-0000-4000-8000-000000000001',
                     'installation_id':'00000000-0000-4000-8000-000000000002',
                     'dispatch_id':'00000000-0000-4000-8000-000000000003',
                     'group_cursor':{'created_at':'2026-10-18T17:54:30.177618+00:00',
                         'request':'00000000-0000-4000-8000-000000000004','task_id':29,
                         'subject':'00000000-0000-4000-8000-000000000001',
                         'installation_id':'00000000-0000-4000-8000-000000000002',
                         'dispatch_id':'00000000-0000-4000-8000-000000000003'},
                     'group_path':str(root/'data-products/participant-pro-ack-inputs'/('a'*64+'.json')),
                     'group_sha256':'a'*64}
            key=material_context_key(context); cursor=context['group_cursor']
            def callback(action,payload):
                events.append((action,copy.deepcopy(payload)))
                if action=='participant_receipts':
                    if payload['after'] is None:return {'contexts':[context],'next_cursor':cursor,'rescan':False}
                    return None
                if action=='enqueue':return {'material_pending':not ready}
            worker=CloudWorker(root,object(),lambda *a:None,postprocessing_callback=callback)
            worker._tick=lambda state:{'state':'idle'}
            worker._save({'phase':'idle'})
            worker.tick(); state=json.loads(worker.path.read_text())
            self.assertEqual(state['participant_pro_cursor'],cursor)
            self.assertEqual(state['postprocessing_contexts'][key],context)
            self.assertIn(key,state['postprocessing_runs'])
            worker._save({'phase':'idle'})
            self.assertEqual(json.loads(worker.path.read_text())['participant_pro_cursor'],cursor)
            worker.tick();self.assertIn(key,json.loads(worker.path.read_text())['postprocessing_runs'])
            ready=True;worker.tick()
            self.assertEqual(json.loads(worker.path.read_text())['postprocessing_runs'],[])
            self.assertEqual(events[0],('participant_receipts',{'after':None}))

    def test_invalid_feed_cannot_advance_cursor(self):
        with tempfile.TemporaryDirectory() as d:
            worker=CloudWorker(Path(d).resolve(),object(),lambda *a:None,
                postprocessing_callback=lambda action,payload:({'contexts':[{'bad':True}],'next_cursor':{'bad':True},'rescan':False} if action=='participant_receipts' else None))
            worker._tick=lambda state:{'state':'idle'};worker._save({'phase':'idle'})
            worker.tick();state=json.loads(worker.path.read_text())
            self.assertNotIn('participant_pro_cursor',state)
            self.assertEqual(worker.postprocessing_error,'participant_pro_feed_failed')

    def test_end_of_scan_resets_cursor_durably(self):
        with tempfile.TemporaryDirectory() as d:
            before={'task_id':29,'request':'00000000-0000-4000-8000-000000000004',
                'created_at':'2026-10-18T17:54:30.177618+00:00',
                'subject':'00000000-0000-4000-8000-000000000001','installation_id':'00000000-0000-4000-8000-000000000002','dispatch_id':'00000000-0000-4000-8000-000000000003'}
            seen=[]
            def callback(action,payload):
                if action=='participant_receipts':
                    seen.append(payload['after'])
                    return {'contexts':[],'next_cursor':None,'rescan':True} if payload['after'] else None
            worker=CloudWorker(Path(d).resolve(),object(),lambda *a:None,postprocessing_callback=callback)
            worker._tick=lambda s:{'state':'idle'};worker._save({'phase':'idle','participant_pro_cursor':before})
            worker.tick();self.assertIsNone(json.loads(worker.path.read_text())['participant_pro_cursor'])
            worker.tick();self.assertEqual(seen,[before,None])

if __name__=='__main__':unittest.main()
