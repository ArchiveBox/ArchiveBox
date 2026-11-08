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
 def test_npm_lock_topology(self):
  for name in ['chrome','abxbus']:
   lock=r.validate_npm_lock(r.HERE/'npm'/name)
   with tempfile.TemporaryDirectory() as d:
    root=Path(d);(root/'package.json').write_bytes((r.HERE/'npm'/name/'package.json').read_bytes())
    bad=copy.deepcopy(lock);key=next(k for k in bad['packages'] if k)
    bad['packages']['../../private/tmp/'+key]=bad['packages'].pop(key)
    (root/'package-lock.json').write_text(json.dumps(bad))
    with self.assertRaises(AssertionError):r.validate_npm_lock(root)
 def test_npm_fixed_schema_errors(self):
  for stage in r.NODE_STAGES:
   self.assertIn(stage,r.STAGES)
   for code in r.NPM_CODES:
    for prefix in ['npm error','npm ERR!']:
     self.assertEqual(r.redact(prefix+' code '+code+'\nhttps://private.example/token\n/private/secret',stage),'npm_'+code.lower())
   for message in ['npm error code PRIVATE_SECRET','npm error code EUSAGE https://private.example','Authorization: Bearer secret','https://private.example','npm error path /private/secret']:
    self.assertEqual(r.redact(message,stage),'unknown')
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
 def test_python_stages_and_private_errors(self):
  for stage in ['python_venv','python_install','python_inspect']:self.assertIn(stage,r.STAGES)
  samples={
   'uv_argument_conflict':"error: the argument '--only-binary <ONLY_BINARY>' cannot be used with '--no-build'",
   'uv_argument_invalid':"error: unexpected argument '--bad' found",
   'python_not_found':'No interpreter found at /private/path',
   'requirements_invalid':'Failed to parse /private/requirements.txt',
   'hash_mismatch':'Hash mismatch for https://private.example/secret',
   'hash_required':'Hashes are required for /private/package',
   'wheel_unavailable':'No compatible wheel for private-package',
   'dependency_resolution':'No solution found when resolving dependencies',
   'download_failed':'Failed to download https://private.example/secret',
   'certificate_failed':'certificate verify failed',
   'python_import_failed':"ModuleNotFoundError: No module named 'private'",
  }
  for category,message in samples.items():
   self.assertEqual(r.redact(message,'python_install'),category)
   self.assertIn(category,r.ERRORS)
  for secret in ['Authorization: Bearer secretvalue','https://private.example/token','-----BEGIN PRIVATE KEY-----private','/private/secret','a'*40000]:
   self.assertEqual(r.redact(secret,'python_install'),'unknown')
   for category,message in samples.items():self.assertEqual(r.redact(message+' '+secret,'python_install'),category)
 def test_setup_report_boundary(self):
  report={'schema':1,'outcome':'setup_failed','versions':{},'sources':{},'stages':[],'transport':[],'resources':[],'container_outcomes':[],'failure_class':'none','checks':{'browser_invoked':False,'sandbox_ready':False,'proof_started':False,'prepared_complete':False,'receipt_verified':False,'tamper_checks':0},'cleanup':{x:True for x in ['key_removed','containers_removed','networks_removed','browser_stopped','private_files_removed']}}
  for stage in ['python_venv','python_install','python_inspect']+sorted(r.NODE_STAGES):
   for error in r.ERRORS:
    report['stages']=[{'stage':stage,'exit':2 if error else 0,'timeout':error=='timeout','error':error}]
    self.assertEqual(r.validate_report(json.loads(json.dumps(report))),report)
  for field in ['stage','error']:
   bad=copy.deepcopy(report);bad['stages'][0][field]='https://private.example/token'
   with self.assertRaises(AssertionError):r.validate_report(bad)
 def test_real_uv_install_argument_regression(self):
  # Exercise the production argument builder with an empty local requirements file.
  # No network, package install, Docker, browser, key, or proof is involved.
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'home').mkdir();requirements=root/'requirements.txt';requirements.write_text('')
   env={'PATH':os.environ['PATH'],'HOME':str(root/'home'),'UV_OFFLINE':'1','UV_NO_CONFIG':'1'}
   created=subprocess.run(['uv','venv','--python',sys.executable,str(root/'venv')],env=env,cwd=root,capture_output=True,text=True)
   self.assertEqual(created.returncode,0)
   args=[str(a) for a in r.python_install_args(root/'venv/bin/python')];args[-1]=str(requirements)
   self.assertIn('--require-hashes',args);self.assertIn('--only-binary',args);self.assertNotIn('--no-build',args)
   broken=subprocess.run(args+['--no-build'],env=env,cwd=root,capture_output=True,text=True)
   self.assertEqual(broken.returncode,2);self.assertEqual(r.redact(broken.stderr,'python_install'),'uv_argument_conflict')
   fixed=subprocess.run(args,env=env,cwd=root,capture_output=True,text=True)
   self.assertEqual(fixed.returncode,0)
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
