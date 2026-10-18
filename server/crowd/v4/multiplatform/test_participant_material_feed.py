import copy,json,os,tempfile,unittest
from pathlib import Path
from participant_material_feed import fetch
from automatic_materials import canonical,sha

FIXTURE=Path(os.environ['CROWD_PRO_ACK_FIXTURE']) if os.environ.get('CROWD_PRO_ACK_FIXTURE') else None

@unittest.skipUnless(FIXTURE,'explicit private ACK fixture required')
class FeedTests(unittest.TestCase):
    def group(self):return json.loads(FIXTURE.read_text())
    def client(self,group):
        class Client:
            def call(self,action,payload):
                assert action=='participant_pro_receipts' and payload=={'after':None,'limit':1}
                return {'schema':'crowd-participant-pro-receipt-feed-v1','groups':[copy.deepcopy(group)],'next_cursor':copy.deepcopy(group['group_cursor']),'has_more':False}
        return Client()
    def test_real_ack_input_is_immutable_and_idempotent(self):
        group=self.group()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();first=fetch(self.client(group),root,None);again=fetch(self.client(group),root,None)
            self.assertEqual(first,again);context=first['contexts'][0];p=Path(context['group_path'])
            self.assertEqual(p.read_bytes(),canonical(group));self.assertEqual(context['group_sha256'],sha(p.read_bytes()))
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'participant_pro_input_changed'):fetch(self.client(group),root,None)
    def test_unreceived_or_changed_body_does_not_create_input(self):
        for mutate in (lambda g:g['receipts'][0]['receipt'].update(gate='rejected'),lambda g:g['receipts'][0]['pro_payload']['record'].update(body='changed')):
            with tempfile.TemporaryDirectory() as d:
                group=self.group();mutate(group)
                with self.assertRaises(ValueError):fetch(self.client(group),Path(d),None)
                self.assertEqual(list(Path(d).rglob('*.json')),[])
    def test_symlink_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();(root/'data-products').mkdir();(root/'elsewhere').mkdir()
            (root/'data-products/participant-pro-ack-inputs').symlink_to(root/'elsewhere')
            with self.assertRaisesRegex(ValueError,'participant_pro_input_unsafe'):fetch(self.client(self.group()),root,None)

if __name__=='__main__':unittest.main()
