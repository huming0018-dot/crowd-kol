"""Finite existing telemetry shape only; temporary steps DB, no cloud/source."""
import tempfile,unittest,uuid
from pathlib import Path
import run_diagnostics as d
from machine_steps import MachineSteps
from pro_xhs_media import FAILURE_REASONS
CODES=sorted(FAILURE_REASONS)
class Tests(unittest.TestCase):
 def test_all_fixed_media_reasons_survive_status(self):
  for code in CODES:
   with self.subTest(code=code):self.assertEqual(d.from_status({'state':'failed','failure_reason':code,'exit_code':74}),{'error_code':code,'exit_code':74})
 def test_all_fixed_media_reasons_validate(self):
  for code in CODES:
   with self.subTest(code=code):self.assertEqual(d.validate({'error_code':code,'exit_code':74},'importing'),{'error_code':code,'exit_code':74})
 def test_old_terminal_mapping_kept(self):
  for state,code in [('completed','run_completed'),('stopped','run_stopped'),('interrupted_unknown','run_outcome_unknown'),('login_required','login_required')]:self.assertEqual(d.from_status({'state':state})['error_code'],code)
 def test_unknown_or_raw_message_stays_unclassified(self):
  for code in ['https://token@private','xhs_media_arbitrary_new_code','secret raw error']:
   self.assertEqual(d.from_status({'state':'failed','failure_reason':code})['error_code'],'run_failure_unclassified')
   with self.assertRaises(ValueError):d.validate({'error_code':code},'importing')
 def test_no_stage_http_or_unsafe_exit_expansion(self):
  for extra in [{'stage':'stream'},{'http_status':403},{'exit_code':True},{'exit_code':1.5},{'exit_code':256}]:
   with self.assertRaises(ValueError):d.validate({'error_code':CODES[0],**extra},'importing')
  with self.assertRaises(ValueError):d.validate({'error_code':CODES[0]},'source_step')
 def test_real_local_steps_retains_finite_error_and_exact_wire(self):
  with tempfile.TemporaryDirectory()as temp:
   class Client:
    def __init__(self):self.calls=[]
    def call(self,action,payload):
     self.calls.append((action,payload));return {'event_ids':[e['event_id']for e in payload['events']]}
   client=Client();steps=MachineSteps(Path(temp)/'steps.sqlite3',client)
   state={'lease':{'run_id':str(uuid.uuid4()),'lease_epoch':1},'phase':'importing','outcome':'failed','run_diagnostic':{'error_code':'xhs_media_http_rejected','exit_code':74}}
   steps.observe(state);steps.flush();self.assertEqual(len(client.calls),1)
   event=client.calls[0][1]['events'][0];self.assertEqual(event['error_code'],'xhs_media_http_rejected');self.assertEqual(event['exit_code'],74)
   self.assertNotIn('http_status',event);self.assertNotIn('stage',event);self.assertEqual(steps.status()['pending'],0)
if __name__=='__main__':unittest.main()
