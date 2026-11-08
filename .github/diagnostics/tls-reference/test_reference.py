"""Offline contract tests. Never starts Docker, Chrome, a server, or a proof."""
import copy,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
import reference as r
class Contract(unittest.TestCase):
 def test_locks(self):
  for name,value in r.PINS['locks'].items():self.assertEqual(r.digest(r.HERE/name),value)
  for name in ('chrome','abxbus'):
   lock=json.loads((r.HERE/'npm'/name/'package-lock.json').read_text())
   for path,package in lock['packages'].items():
    if path:self.assertTrue(package['resolved'].startswith('https://registry.npmjs.org/'));self.assertTrue(package['integrity'].startswith('sha512-'))
 def test_one_shot(self):
  with tempfile.TemporaryDirectory() as d:
   r.consume(d)
   with self.assertRaises(FileExistsError):r.consume(d)
 def test_dependency_escape(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'owned';root.mkdir();(root/'escape').symlink_to('/etc')
   with self.assertRaises(AssertionError):r.tree_hash(root)
 def test_real_failure_and_timeout(self):
  with tempfile.TemporaryDirectory() as d:
   result=subprocess.run(['ls',str(Path(d)/'missing')],capture_output=True,text=True)
   self.assertNotEqual(result.returncode,0);self.assertTrue(result.stderr);self.assertEqual(r.redact(result.stderr),'unknown')
  with self.assertRaises(subprocess.TimeoutExpired) as caught:subprocess.run(['sh','-c','ls /a-certainly-missing-tls-reference-path >&2; exec sleep 10'],capture_output=True,timeout=.2)
  self.assertTrue(caught.exception.stderr);self.assertEqual(r.redact(caught.exception.stderr),'unknown')
 def test_redaction(self):
  for value in ['X-Custom: private value\npayload: private words','Authorization: Bearer secretvalue','https://example.com/private','-----BEGIN PRIVATE KEY-----secretbytes']:
   self.assertEqual(r.redact(value),'unknown')
  self.assertEqual(r.redact('failed to stat parent: stat /private/value: no such file'),'snapshot_parent_missing')
 def test_cleanup_no_journal(self):
  import cleanup
  with tempfile.TemporaryDirectory() as d:
   self.assertTrue(cleanup.cleanup(d))
 def test_cleanup_rejects_unowned_journal(self):
  import cleanup
  with tempfile.TemporaryDirectory() as d:
   (Path(d)/'tls-ownership.json').write_text(json.dumps({'work':'/not-owned','token':'a'*32,'project':'abx-tls-'+('a'*16)}))
   with self.assertRaises(AssertionError):cleanup.cleanup(d)
 def test_uninspectable_process_is_uncertain(self):
  import cleanup
  with tempfile.TemporaryDirectory() as d:
   process=Path(d)/'123';process.mkdir();(process/'environ').mkdir()
   candidates,uncertain=cleanup.scan_processes(d,'a'*32)
   self.assertEqual(candidates,[]);self.assertTrue(uncertain)
   (process/'environ').rmdir();process.rmdir()
   self.assertEqual(cleanup.scan_processes(d,'a'*32),([],False))
 def test_signal_error_does_not_raise(self):
  import cleanup
  self.assertFalse(cleanup.signal_owned(os.getpid(),999999))
 def test_compose_limits(self):
  compose=r.gateway_compose(Path('/test'),'sha256:'+'0'*64,'test')
  a,b=compose['services']['verifier'],compose['services']['gateway']
  self.assertEqual((a['mem_limit'],a['memswap_limit'],a['cpus'],a['pids_limit']),('3g','3g',2,128))
  self.assertEqual((b['mem_limit'],b['cpus'],b['pids_limit']),('256m',1,64))
  for service in [a,b]:self.assertEqual(service['cap_drop'],['ALL']);self.assertTrue(service['read_only']);self.assertEqual(service['security_opt'],['no-new-privileges:true'])
  self.assertTrue(compose['networks']['private']['internal']);self.assertEqual(b['ports'],['127.0.0.1:0:7047'])
 def test_branch_upload_contract(self):
  workflow=r.HERE.parents[1]/'workflows/diagnose-canva.yml'
  if not workflow.exists():workflow=r.HERE.parents[1]/'workflows/diagnose-canva.yml'
  text=workflow.read_text()
  self.assertIn('timeout-minutes: 16',text);self.assertIn('timeout-minutes: 20',text);self.assertIn('Always remove owned private state',text);self.assertIn(r.BRANCH,text);self.assertIn("workflow_dispatch: {}",text)
  for forbidden in ['secrets.', 'pull_request:', 'push:', 'schedule:', 'workflow_run:', 'sudo ', '--no-sandbox', 'privileged:']:self.assertNotIn(forbidden,text)
  self.assertIn('path: ${{ runner.temp }}/tls-safe/summary.json',text)
  self.assertIn("steps.boundary.outcome == 'success'",text)
  source=(r.HERE/'reference.py').read_text()
  self.assertNotIn("['logs'",source);self.assertIn("shutil.rmtree(work)",source);self.assertIn("capture.pid,signal.SIGINT",source)
if __name__=='__main__':
 if len(sys.argv)==3 and sys.argv[1]=='--validate':
  path=Path(sys.argv[2]);r.validate_report(json.loads(path.read_text()));assert set(p.name for p in path.parent.iterdir())=={'summary.json'}
 else:unittest.main()
