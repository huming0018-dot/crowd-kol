import hashlib,os,subprocess,sys,tempfile,unittest
from pathlib import Path
class Tests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.bin=self.root/'bin';self.bin.mkdir();self.home=self.root/'home';self.home.mkdir();self.trace=self.root/'trace';self.script=Path(__file__).with_name('install-linux.sh');self.env={**os.environ,'HOME':str(self.home),'PATH':str(self.bin)+':/usr/bin:/bin','TRACE':str(self.trace)}
  if sys.platform=='darwin':
   self.tool('stat','case "$2" in %u) exec /usr/bin/stat -f %u "$3";; %a) exec /usr/bin/stat -f %Lp "$3";; %h) exec /usr/bin/stat -f %l "$3";; esac');self.tool('sha256sum','exec /usr/bin/shasum -a 256 "$@"')
  self.tool('git','exit 0');self.tool('uname','if [ "$1" = -s ]; then echo Linux; else echo aarch64; fi')
 def tearDown(self):self.t.cleanup()
 def tool(self,name,body):
  p=self.bin/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o700);return p
 def run_script(self,*args):return subprocess.run(['/bin/sh',str(self.script),*map(str,args)],env=self.env,capture_output=True)
 def test_help_never_bootstraps_or_changes_home(self):
  value=self.run_script('--help');self.assertEqual(value.returncode,0);self.assertFalse(list(self.home.iterdir()));self.assertIn(b'not downloaded',value.stdout)
 def test_existing_uv_and_python_reused_without_network(self):
  uv=self.tool('uv',"echo should_not_run >>\"$TRACE\";exit 90");self.tool('python3.12','printf "%s\\n" "$*" >>"$TRACE";exit 0');self.tool('curl','exit 91')
  value=self.run_script('--bootstrap-only','--uv',uv);self.assertEqual(value.returncode,0,value.stderr);self.assertNotIn('should_not_run',self.trace.read_text())
 def test_missing_python_uses_original_uv_fixed_no_bin_install(self):
  python=self.root/'managed-python';python.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >>"$TRACE"\n');python.chmod(0o700)
  uv=self.tool('uv','printf "%s\\n" "$*" >>'+str(self.trace)+';case "$*" in *"python find"*) echo '+str(python)+';; esac')
  value=self.run_script('--bootstrap-only','--uv',uv);self.assertEqual(value.returncode,0,value.stderr);trace=self.trace.read_text();self.assertIn('--no-config python install --no-bin 3.12.14',trace);self.assertIn('--managed-python --no-python-downloads 3.12.14',trace);self.assertNotIn('--default',trace)
 def test_archive_integrity_failure_never_executes_download(self):
  # Force automatic private uv, not an existing user tool.
  self.tool('curl','while [ "$1" != -o ]; do shift; done;printf untrusted >"$2"');self.tool('sha256sum','exit 1')
  value=self.run_script('--bootstrap-only');self.assertEqual(value.returncode,2);self.assertIn(b'uv_archive_changed',value.stderr);self.assertFalse(any(p.name.startswith('uv-0.12.7')for p in self.home.rglob('*')))
 def test_managed_record_checked_without_download_or_write(self):
  exe=self.tool('managed-python','printf checked >>"$TRACE"');base=self.home/'.local/share/CrowdV4Updater/bootstrap';base.mkdir(parents=True);record=base/'python312.record';record.write_text(str(exe)+'\n'+hashlib.sha256(exe.read_bytes()).hexdigest()+'\n');record.chmod(0o600);before=record.read_bytes()
  value=self.run_script('--python-path');self.assertEqual(value.returncode,0,value.stderr);self.assertEqual(value.stdout.decode().strip(),str(exe));self.assertEqual(before,record.read_bytes());self.assertEqual(self.trace.read_text(),'checked')
 def test_changed_managed_interpreter_never_executed(self):
  exe=self.tool('managed-python','echo executed >>"$TRACE"');base=self.home/'.local/share/CrowdV4Updater/bootstrap';base.mkdir(parents=True);record=base/'python312.record';record.write_text(str(exe)+'\n'+'0'*64+'\n');record.chmod(0o600)
  value=self.run_script('--python-path');self.assertEqual(value.returncode,2);self.assertIn(b'python312_changed',value.stderr);self.assertFalse(self.trace.exists())
 def test_check_without_python_does_not_install_or_create_home(self):
  value=self.run_script('--check','--root',self.root/'node');self.assertEqual(value.returncode,2);self.assertIn(b'python312_not_installed',value.stderr);self.assertEqual(list(self.home.iterdir()),[])
 def test_existing_node_bypasses_uv_download_before_reuse(self):
  node=self.root/'node';node.mkdir();(node/'node-install.json').write_text('validated by original Python installer')
  self.tool('python3.12','printf "%s\\n" "$*" >>"$TRACE";exit 0');self.tool('curl','echo forbidden >>"$TRACE";exit 89')
  value=self.run_script('--root',node,'--upgrade');self.assertEqual(value.returncode,0,value.stderr);trace=self.trace.read_text();self.assertNotIn('forbidden',trace);self.assertIn('install-linux.py --root',trace);self.assertIn('--upgrade',trace)
 def test_existing_node_equals_root_bypasses_download(self):
  run=self.run_script
  self.run_script=lambda *args:run('--root='+str(args[1]),*args[2:])
  self.test_existing_node_bypasses_uv_download_before_reuse()
if __name__=='__main__':unittest.main()
