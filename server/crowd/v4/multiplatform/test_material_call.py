"""Portable command-boundary regression; real material integration is separate."""
from pathlib import Path
import hashlib,os,sys,tempfile,unittest
from workbench_material_call import command,_digest

class MaterialCallTests(unittest.TestCase):
 def test_exact_argv_and_mutation_rejected(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp).resolve();script=root/'script.py';request=root/'request.json';script.write_text('pass\n');request.write_text('{}')
   config={'python':sys.executable,'script':str(script),'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),'request':str(request),'request_sha256':hashlib.sha256(request.read_bytes()).hexdigest()}
   self.assertEqual(command(config),[sys.executable,'-B',str(script),'--request',str(request),'--action','read','--format','html'])
   request.write_text('{"changed":true}')
   with self.assertRaises(ValueError):command(config)
 def test_nonregular_and_symlink_rejected(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp).resolve();file=root/'file';file.write_text('x');link=root/'link';link.symlink_to(file)
   for path in [root,link]:
    with self.assertRaises(ValueError):_digest(path)
   if hasattr(os,'mkfifo'):
    fifo=root/'fifo';os.mkfifo(fifo)
    with self.assertRaises(ValueError):_digest(fifo)
 def test_bad_shapes_rejected(self):
  for config in [None,[],True,{},dict(python=False,script=False,script_sha256=False,request=False,request_sha256=False)]:
   with self.subTest(config=config),self.assertRaises(ValueError):command(config)

if __name__=='__main__':unittest.main()
