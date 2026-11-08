"""One public, source-pinned Linux TLSNotary reference; never a release workflow."""
from pathlib import Path
import argparse,hashlib,json,os,platform,re,shutil,signal,stat,subprocess,sys,tarfile,tempfile,threading,time,urllib.request,uuid,zipfile

import sandbox_checks
HERE=Path(__file__).resolve().parent
BRANCH='refs/heads/diagnostics/canva-font-validation-rc78'
URL='https://www.canva.com/design/DAGudZAYlEE/VzrUrqpV2RhkVHCg43lvKQ/view?mode=preview&utm_campaign=designshare&utm_content=DAGudZAYlEE&utm_medium=link&utm_source=publishsharelink'
DOCKER=['docker','--host','unix:///var/run/docker.sock']
STAGES={'preflight','python','python_venv','python_install','python_inspect','downloads','node_dependencies','node_chrome_install','node_abxbus_install','node_inspect','sandbox','gateway_build','services','proof','verification','cleanup'}
SOURCE_NAMES={'wheel','extension','chrome','node','requirements','chrome_lock','abxbus_lock','gateway_tree','client_tree','official_extension_tree','prepared_extension_tree','prepared_wasm','prepared_offscreen','checker','verifier_module','node_modules_tree','gateway_image'}

def sha(data):return hashlib.sha256(data).hexdigest()
def digest(path):return sha(Path(path).read_bytes())
def tree_hash(root):
 root=Path(root).resolve();entries=[]
 for path in sorted(root.rglob('*')):
  if '__pycache__' in path.parts:continue
  if path.is_symlink():
   assert path.resolve().is_relative_to(root),'Dependency symlink escapes owned root'
   entries.append((str(path.relative_to(root)),os.readlink(path)))
  elif path.is_file():entries.append((str(path.relative_to(root)),digest(path)))
 return sha(json.dumps(entries,separators=(',',':')).encode())
def consume(root):
 marker=Path(root)/'proof-consumed';marker.open('x').close()
ERRORS={'','unknown','timeout','permission_denied','snapshot_parent_missing','snapshot_exists','image_missing','resource_exhausted','runtime_failure','connection_failed','invariant_failed'}
PYTHON_ERRORS={
 'uv_argument_conflict':r"error: the argument .* cannot be used with",
 'uv_argument_invalid':r"error: (?:unexpected argument|invalid value|a value is required)",
 'python_not_found':r'no (?:interpreter|python installation) found|failed to query python interpreter|interpreter not found',
 'requirements_invalid':r'failed to parse|unable to parse|error parsing',
 'hash_mismatch':r'hash mismatch|hashes? (?:do not|does not|did not) match',
 'hash_required':r'hashes are required|must have a hash|must be pinned',
 'wheel_unavailable':r'no compatible wheel|no wheels with a matching|no binary distribution|no usable wheels',
 'dependency_resolution':r'no solution found|unsatisfiable',
 'certificate_failed':r'certificate verify failed|invalid peer certificate|unknownissuer',
 'download_failed':r'failed to download|failed to fetch|error sending request',
 'python_import_failed':r'modulenotfounderror:|importerror:',
}
NODE_STAGES={'node_chrome_install','node_abxbus_install','node_inspect'}
NPM_CODES={'EUSAGE','ENOTCACHED','ELOCKVERIFY','EJSONPARSE','ERESOLVE','ETARGET','EINTEGRITY','ENOENT','EACCES','EPERM','ENOSPC','ENOTFOUND','EAI_AGAIN','ECONNREFUSED','ECONNRESET','ETIMEDOUT','ENETUNREACH','E401','E403','E404','CERT_HAS_EXPIRED','UNABLE_TO_VERIFY_LEAF_SIGNATURE','SELF_SIGNED_CERT_IN_CHAIN'}
ERRORS.update('npm_'+code.lower() for code in NPM_CODES)
ERRORS.update(PYTHON_ERRORS)
def npm_install_args(npm):
 # npm 11.19 treats --prefix outside cwd as a local-package edge; run in target instead.
 return [npm,'ci','--ignore-scripts','--no-audit','--no-fund','--userconfig=/dev/null','--registry=https://registry.npmjs.org']
def validate_npm_lock(directory):
 directory=Path(directory);package=json.loads((directory/'package.json').read_text());lock=json.loads((directory/'package-lock.json').read_text())
 assert lock['lockfileVersion']==3 and not str(lock.get('version','')).startswith('file:')
 entries=lock['packages'];assert entries[''].get('dependencies',{})==package.get('dependencies',{})
 for location,entry in entries.items():
  if not location:continue
  assert location.startswith('node_modules/') and not any(p in {'','..','.'} for p in location.split('/'))
  assert not entry.get('link') and entry['resolved'].startswith('https://registry.npmjs.org/') and entry['integrity'].startswith('sha512-')
 for name,version in package.get('dependencies',{}).items():assert entries['node_modules/'+name]['version']==version
 return lock

ERRORS.update({'command_missing','process_start_failed'})
STAGES.update(sandbox_checks.STAGES);ERRORS.update(sandbox_checks.ERRORS)
def python_install_args(py):
 # --no-build is an alias of --only-binary :all:, and uv rejects combining them.
 return ['uv','pip','install','--python',py,'--require-hashes','--only-binary',':all:','-r',HERE/'requirements.txt']
def redact(text,stage=None):
 if isinstance(text,bytes):text=text.decode('utf8','replace')
 text=(text or '')[:32768]
 if stage in NODE_STAGES:
  for code in re.findall(r'^npm (?:error|ERR!) code ([A-Z0-9_]+)\s*$',text,re.MULTILINE):
   if code in NPM_CODES:return 'npm_'+code.lower()
 text=text.lower()
 if stage in {'python_venv','python_install','python_inspect'}:
  for category,pattern in PYTHON_ERRORS.items():
   if re.search(pattern,text):return category
 for category,pattern in [('snapshot_parent_missing','failed to stat parent'),('snapshot_exists','already exists'),('permission_denied','permission denied|operation not permitted'),('image_missing','no such image|pull access denied'),('resource_exhausted','no space left|cannot allocate memory'),('runtime_failure','oci runtime|failed to create.*task'),('connection_failed','cannot connect to the docker daemon')]:
  if re.search(pattern,text):return category
 return 'unknown'

def validate_report(report):
 assert set(report)=={'schema','outcome','versions','sources','stages','transport','resources','container_outcomes','failure_class','checks','cleanup'}
 assert report['schema']==1 and report['outcome'] in {'setup_failed','proof_failed','verified','cleanup_failed'}
 assert set(report['versions'])<={'python','node','chrome','plugins','abx_dl','sandbox_helper'}
 assert all(re.fullmatch(r'[0-9A-Za-z.+:~_-]{1,80}',v) for v in report['versions'].values())
 assert set(report['sources'])<=SOURCE_NAMES
 assert all(re.fullmatch('[0-9a-f]{64}',v) for v in report['sources'].values())
 for item in report['stages']:
  assert set(item)=={'stage','exit','timeout','error'} and item['stage'] in STAGES
  assert item['exit'] is None or type(item['exit']) is int
  assert type(item['timeout']) is bool and item['error'] in ERRORS
  assert not re.search(r'https?://|-----BEGIN|(?<![\w])/[A-Za-z]|\b[0-9a-f]{12,}\b',item['error'])
 for item in report['transport']:
  assert set(item)<={'event','channel','peer','code','client_bytes','backend_bytes','sent_bytes','received_bytes','reason'}
  assert item['event'] in {'registration','control_close','relay_close','proxy_close','session_close','admission_memory'}
  for key,value in item.items():
   if key in {'code','client_bytes','backend_bytes','sent_bytes','received_bytes'}:assert type(value) is int and value>=0
   elif key=='channel':assert value in {'control','verifier'}
   elif key=='peer':assert value in {'client','backend','server'}
   elif key=='reason':assert value in {'memory','control_backend','control_client','control_close','deadline','registration','proxy_send_cap','proxy_receive_cap','forwarding','relay_cap','protocol','other'}
 assert report['failure_class'] in {'none','zk_execution_closed','protocol_closed','other'}
 for item in report['container_outcomes']:
  assert set(item)=={'service','exit','oom','running'} and item['service'] in {'gateway','verifier'}
  assert type(item['exit']) is int and type(item['oom']) is bool and type(item['running']) is bool
 for row in report['resources']:
  assert set(row)=={'elapsed_ms','verifier','gateway'} and type(row['elapsed_ms']) is int
  for service in ['verifier','gateway']:
   assert set(row[service])<={'current','peak','max','oom','oom_kill','swap_current','swap_max','unavailable'}
   assert all(type(v) is int and v>=0 for v in row[service].values())
 assert set(report['checks'])=={'chrome_version_invoked','chrome_version_completed','helper_present','browser_invoked','sandbox_ready','proof_started','prepared_complete','receipt_verified','tamper_checks'}
 assert all(type(report['checks'][x]) is bool for x in ['chrome_version_invoked','chrome_version_completed','helper_present','browser_invoked','sandbox_ready','proof_started','prepared_complete','receipt_verified'])
 assert report['checks']['tamper_checks'] in {0,5}
 assert set(report['cleanup'])=={'key_removed','containers_removed','networks_removed','browser_stopped','private_files_removed'}
 assert all(type(v) is bool for v in report['cleanup'].values())
 return report

def download(spec,dest):
 assert spec['url'].startswith('https://')
 with urllib.request.urlopen(spec['url'],timeout=60) as response:body=response.read()
 assert sha(body)==spec['sha256'],'Input digest mismatch'
 Path(dest).write_bytes(body);return Path(dest)
def unzip(source,dest):
 dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(source) as archive:
  for info in archive.infolist():
   path=dest/info.filename
   assert path.resolve().is_relative_to(dest.resolve())
   assert not stat.S_ISLNK(info.external_attr>>16)
   archive.extract(info,dest)
   if not info.is_dir():path.chmod((info.external_attr>>16)&0o777 or 0o644)
def gateway_compose(work,image,token):
 common={'platform':'linux/amd64','cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'read_only':True,'ulimits':{'core':{'soft':0,'hard':0}},'restart':'no','logging':{'driver':'none'},'pull_policy':'never','labels':{'io.archivebox.tls.reference-token':token}}
 return {'services':{'verifier':{**common,'image':PINS['verifier'],'init':True,'command':['timeout','--kill-after=30s','4h','/app/tlsn-verifier-server'],'environment':{'PORT':'7047','MALLOC_MMAP_THRESHOLD_':'131072','MALLOC_TRIM_THRESHOLD_':'131072'},'volumes':[str(work/'verifier-config.yaml')+':/app/config.yaml:ro'],'networks':['private'],'mem_limit':'3g','memswap_limit':'3g','cpus':2,'pids_limit':128,'stop_grace_period':'35s'},'gateway':{**common,'image':image,'user':f'{os.getuid()}:{os.getgid()}','environment':{'TLSNOTARY_MIN_AVAILABLE_MEMORY_MB':'1024','TLSNOTARY_MAX_SESSIONS':'1','NODE_DISABLE_COMPILE_CACHE':'1'},'ports':['127.0.0.1:0:7047'],'volumes':[str(work/'state')+':/state:ro'],'networks':['private','public'],'mem_limit':'256m','cpus':1,'pids_limit':64}},'networks':{'private':{'internal':True,'labels':{'io.archivebox.tls.reference-token':token}},'public':{'labels':{'io.archivebox.tls.reference-token':token}}}}
PINS=json.loads((HERE/'pins.json').read_text())

def run(root,safe):
 root=Path(root);safe=Path(safe);safe.mkdir(parents=True,exist_ok=True)
 assert not (safe/'summary.json').exists(),'No repeat attempt'
 work=Path(tempfile.mkdtemp(prefix='tls-private-',dir=root));token=uuid.uuid4().hex;project='abx-tls-'+token[:16]
 report={'schema':1,'outcome':'setup_failed','versions':{},'sources':{},'stages':[],'transport':[],'resources':[],'container_outcomes':[],'failure_class':'none','checks':{'chrome_version_invoked':False,'chrome_version_completed':False,'helper_present':False,'browser_invoked':False,'sandbox_ready':False,'proof_started':False,'prepared_complete':False,'receipt_verified':False,'tamper_checks':0},'cleanup':{x:False for x in ['key_removed','containers_removed','networks_removed','browser_stopped','private_files_removed']}}
 journal=root/'tls-ownership.json'
 from cleanup import persist_journal,mark_browser_invoked,mark_version_state
 persist_journal(journal,{'work':str(work),'token':token,'project':project,'browser_invoked':False,'chrome_version_invoked':False,'chrome_version_completed':False},create=True)
 stage='preflight';ids={};compose=None;service_attempted=False;observer=None;capture=None;stop=threading.Event();threads=[];start=time.monotonic();failed=False
 env={'ABX_TLS_REFERENCE_OWNER':token,'PATH':os.environ['PATH'],'HOME':str(work/'home'),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','NODE_DISABLE_COMPILE_CACHE':'1'}
 for d in ['home','state','tmp','capture','personas','lib','downloads']: (work/d).mkdir()
 def cmd(args,timeout=60,use_env=None,cwd=None):
  try:result=subprocess.run([str(x) for x in args],env=use_env or env,capture_output=True,text=True,timeout=timeout,cwd=work if cwd is None else cwd)
  except subprocess.TimeoutExpired as error:
   report['stages'].append({'stage':stage,'exit':None,'timeout':True,'error':'timeout'})
   raise RuntimeError('Command timeout') from None
  except OSError as error:
   category='command_missing' if isinstance(error,FileNotFoundError) else 'permission_denied' if isinstance(error,PermissionError) else 'process_start_failed'
   report['stages'].append({'stage':stage,'exit':None,'timeout':False,'error':category})
   raise RuntimeError('Command start failure') from None
  if result.returncode:
   report['stages'].append({'stage':stage,'exit':result.returncode,'timeout':False,'error':redact(result.stderr,stage)})
   raise RuntimeError('Command failure')
  if stage in {'python_venv','python_install','python_inspect'}|NODE_STAGES:report['stages'].append({'stage':stage,'exit':0,'timeout':False,'error':''})
  return result.stdout.strip()
 def owned(cid):
  labels=json.loads(cmd(DOCKER+['inspect',cid,'--format','{{json .Config.Labels}}']))
  assert labels.get('com.docker.compose.project')==project and labels.get('io.archivebox.tls.reference-token')==token
 def cgroup(cid):
  owned(cid)
  text=cmd(DOCKER+['exec',cid,'/bin/sh','-c','for n in memory.current memory.peak memory.max memory.events memory.swap.current memory.swap.max; do if [ -r /sys/fs/cgroup/$n ]; then echo "$n"; cat /sys/fs/cgroup/$n; fi; done'],timeout=5)
  result={};key=None
  mapping={'memory.current':'current','memory.peak':'peak','memory.max':'max','memory.swap.current':'swap_current','memory.swap.max':'swap_max'}
  for line in text.splitlines():
   if line.startswith('memory.'):key=line;continue
   if key in mapping and line.isdigit():result[mapping[key]]=int(line)
   if key=='memory.events' and re.fullmatch(r'oom(?:_kill)? \d+',line):k,v=line.split();result[k]=int(v)
  return result
 def resources():
  while not stop.wait(1):
   row={'elapsed_ms':int(1000*(time.monotonic()-start)),'verifier':{},'gateway':{}}
   for name,cid in ids.items():
    try:row[name]=cgroup(cid)
    except Exception:row[name]={'unavailable':1}
   report['resources'].append(row)
 def transport():
  for line in observer.stdout:
   line=line.strip();record=None
   if re.fullmatch(r'registration accepted [a-f0-9]{12} [a-f0-9]{12}',line):record={'event':'registration'}
   m=re.fullmatch(r'control closed [a-f0-9]{12} (\d+)',line)
   if m:record={'event':'control_close','code':int(m[1])}
   m=re.fullmatch(r'relay closed [a-f0-9]{12} (control|verifier) (client|backend) (\d+) \{ client: (\d+), backend: (\d+) \}',line)
   if m:record={'event':'relay_close','channel':m[1],'peer':m[2],'code':int(m[3]),'client_bytes':int(m[4]),'backend_bytes':int(m[5])}
   m=re.fullmatch(r'proxy closed [a-f0-9]{12} (client|server) (\d+|true|false) \{ sent: (\d+), received: (\d+) \}',line)
   if m:record={'event':'proxy_close','peer':m[1],'code':int(m[2]) if m[2].isdigit() else int(m[2]=='true'),'sent_bytes':int(m[3]),'received_bytes':int(m[4])}
   m=re.fullmatch(r'session closed [a-f0-9]{12} (.+)',line)
   if m:
    reasons={'insufficient available memory':'memory','control backend error':'control_backend','control client error':'control_client','control closed':'control_close','session deadline':'deadline','registration deadline':'registration','registration rejected':'registration','proxy send cap':'proxy_send_cap','proxy receive cap':'proxy_receive_cap','proxy forwarding error':'forwarding','relay byte cap':'relay_cap','invalid reveal config':'protocol'}
    record={'event':'session_close','reason':reasons.get(m[1],'other')}
   if line=='proof rejected: insufficient available memory':record={'event':'admission_memory'}
   if record and len(report['transport'])<300:report['transport'].append(record)
 def prepared(original):
  prior={};expected={str(p.relative_to(original)) for p in original.rglob('*') if p.is_file()}
  while not stop.wait(.2):
   for base in [work/'personas',work/'tmp',work/'capture']:
    for directory in base.glob('**/.tlsnotary/0.1.0.1501-export2-mux1'):
     try:
      current={str(p.relative_to(directory)):digest(p) for p in directory.rglob('*') if p.is_file()}
      valid=set(current)==expected and all(current.get(n)==PINS['extension']['wasm_patched'] for n in ['tlsn_wasm_bg.wasm','c215ca8b495a7eadf02b.wasm']) and current.get('offscreen.bundle.js')=='3842f72e8e6c1794e97b690a410a3612b451cc1854146ac2a9be0f2eedab2cea'
      if valid and current==prior:
       report['sources']['prepared_extension_tree']=sha(json.dumps(sorted(current.items())).encode());report['sources']['prepared_wasm']=current['tlsn_wasm_bg.wasm'];report['sources']['prepared_offscreen']=current['offscreen.bundle.js'];report['checks']['prepared_complete']=True;return
      prior=current if valid else {}
     except FileNotFoundError:prior={}
 try:
  assert os.environ.get('GITHUB_EVENT_NAME')=='workflow_dispatch' and os.environ.get('GITHUB_REF')==BRANCH
  assert platform.system()=='Linux' and platform.machine()=='x86_64' and sys.version.split()[0]==PINS['python']
  assert Path('/var/run/docker.sock').is_socket();assert not os.environ.get('DOCKER_HOST') and not os.environ.get('DOCKER_CONTEXT')
  for name,value in PINS['locks'].items():assert digest(HERE/name)==value
  assert not cmd(DOCKER+['ps','-aq','--filter','label=com.docker.compose.project='+project])
  assert not cmd(DOCKER+['network','ls','-q','--filter','label=com.docker.compose.project='+project])
  stage='python_venv'
  cmd(['uv','venv','--python',sys.executable,str(work/'venv')])
  py=work/'venv/bin/python'
  stage='python_install'
  cmd(python_install_args(py),timeout=180)
  report['sources']['requirements']=digest(HERE/'requirements.txt')
  stage='python_inspect'
  installed=json.loads(cmd([py,'-c',"import importlib.metadata,json,abx_plugins;print(json.dumps({'plugins':importlib.metadata.version('abx-plugins'),'abx_dl':importlib.metadata.version('abx-dl'),'path':abx_plugins.__file__}))"]))
  assert installed['plugins']==PINS['plugins'] and installed['abx_dl']==PINS['abx_dl'];plugin=Path(installed['path']).parent
  assert plugin.resolve().is_relative_to(work.resolve())
  report['versions'].update(python=PINS['python'],plugins=PINS['plugins'],abx_dl=PINS['abx_dl']);report['sources']['client_tree']=tree_hash(plugin)
  stage='downloads'
  wheel=download(PINS['plugin_wheel'],work/'downloads/plugins.whl');report['sources']['wheel']=digest(wheel)
  with zipfile.ZipFile(wheel) as archive:
   for p in plugin.rglob('*'):
    if p.is_file() and '__pycache__' not in p.parts:assert p.read_bytes()==archive.read('abx_plugins/'+str(p.relative_to(plugin)))
  for name in ['node','chrome','extension']:
   f=download(PINS[name],work/'downloads'/name);report['sources'][name]=digest(f)
  with tarfile.open(work/'downloads/node') as archive:archive.extractall(work/'node',filter='data')
  node=work/'node/node-v24.22.1-linux-x64/bin/node';npm=node.with_name('npm');unzip(work/'downloads/chrome',work/'chrome');chrome=work/'chrome/chrome-linux64/chrome'
  unzip(work/'downloads/extension',work/'official-extension');original=work/'official-extension'
  assert (original/'manifest.json').exists() and json.loads((original/'manifest.json').read_text())['version']==PINS['extension']['version']
  report['sources']['official_extension_tree']=tree_hash(original)
  extension_dir=work/'lib/chromewebstore/extensions';extension_dir.mkdir(parents=True)
  (extension_dir/'tlsnotary.extension.json').write_text(json.dumps({'unpacked_path':str(original),'name':'tlsnotary','webstore_id':'gcfkkledipjbgdbimfpijgbkhajiaaph'}))
  env['PATH']=str(node.parent)+':'+str(work/'venv/bin')+':'+env['PATH']
  assert PINS['node']['version'] in cmd([node,'--version'])
  mark_version_state(journal,False);report['checks']['chrome_version_invoked']=True
  chrome_version=cmd([chrome,'--version'])
  mark_version_state(journal,True);report['checks']['chrome_version_completed']=True
  assert PINS['chrome']['version'] in chrome_version;report['versions'].update(node=PINS['node']['version'],chrome=PINS['chrome']['version'])
  stage='node_dependencies'
  for name in ['chrome','abxbus']:
   stage='node_'+name+'_install';validate_npm_lock(HERE/'npm'/name)
   target=work/'lib/pnpm/packages'/name;target.mkdir(parents=True)
   for filename in ['package.json','package-lock.json']:shutil.copyfile(HERE/'npm'/name/filename,target/filename)
   cmd(npm_install_args(npm),timeout=120,cwd=target)
   report['sources'][name+'_lock']=digest(target/'package-lock.json')
  stage='node_inspect'
  report['sources']['node_modules_tree']=tree_hash(work/'lib/pnpm/packages')
  stage='sandbox_helper_stat'
  helper=Path(sandbox_checks.HELPER);report['checks']['helper_present']=helper.exists()
  if report['checks']['helper_present']:
   info=helper.stat();sandbox_checks.validate_stat(info.st_uid,stat.S_IMODE(info.st_mode))
   stage='sandbox_helper_owner';package=sandbox_checks.package_owner(cmd(['dpkg-query','-S',str(helper)]))
   stage='sandbox_helper_checksum'
   metadata=cmd(['dpkg-query','--control-show',package,'md5sums'])
   sandbox_checks.checksum_match(metadata,hashlib.md5(helper.read_bytes()).hexdigest())
   stage='sandbox_helper_version'
   env['CHROME_DEVEL_SANDBOX']=str(helper);report['versions']['sandbox_helper']=cmd(['dpkg-query','-W','-f=${Version}',package])
  stage='sandbox_probe';mark_browser_invoked(journal);report['checks']['browser_invoked']=True
  page=cmd(sandbox_checks.probe_args(chrome,work/'sandbox-profile'),timeout=20)
  stage='sandbox_page';sandbox_checks.validate_page(page)
  report['checks']['sandbox_ready']=True
  stage='gateway_build';server=plugin/'plugins/tlsnotary/server';build=work/'build';build.mkdir()
  for name,value in PINS['gateway_files'].items():
   assert digest(server/name)==value;target=build/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(server/name,target)
  report['sources']['gateway_tree']=tree_hash(build)
  assert digest(server/'verifier-config.yaml')==PINS['verifier_config_sha256'];shutil.copyfile(server/'verifier-config.yaml',work/'verifier-config.yaml')
  for image in [PINS['node_base'],PINS['verifier']]:
   cmd(DOCKER+['pull','--platform','linux/amd64',image],timeout=180)
   metadata=json.loads(cmd(DOCKER+['image','inspect',image]))[0]
   assert metadata['Architecture']=='amd64' and metadata['Os']=='linux'
   assert any(d.endswith('@'+image.split('@')[1]) for d in metadata['RepoDigests'])
  cmd(DOCKER+['build','--platform','linux/amd64','--pull=false','--no-cache','--iidfile',str(work/'gateway.id'),str(build)],timeout=180)
  image=(work/'gateway.id').read_text().strip();assert re.fullmatch('sha256:[0-9a-f]{64}',image);report['sources']['gateway_image']=image[7:]
  stage='services';(work/'compose.json').write_text(json.dumps(gateway_compose(work,image,token)));(work/'empty.env').touch()
  compose=DOCKER+['compose','--env-file',str(work/'empty.env'),'-p',project,'-f',str(work/'compose.json')]
  cmd(compose+['config','--quiet']);cmd(['openssl','genpkey','-algorithm','ED25519','-out',work/'state/signing.pem']);(work/'state/signing.pem').chmod(0o600)
  service_attempted=True;cmd(compose+['up','--detach','--no-build','--pull','never','verifier','gateway'],timeout=60)
  for service in ['verifier','gateway']:ids[service]=cmd(compose+['ps','-q',service]);owned(ids[service])
  observer=subprocess.Popen(DOCKER+['attach','--no-stdin','--sig-proxy=false',ids['gateway']],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
  thread=threading.Thread(target=transport,daemon=True);thread.start();threads.append(thread)
  address=cmd(compose+['port','gateway','7047']);assert re.fullmatch(r'127\.0\.0\.1:\d+',address);endpoint='http://'+address
  key=None
  for _ in range(50):
   try:
    with urllib.request.urlopen(endpoint+'/key',timeout=1) as response:key=json.load(response)['publicKey']
    break
   except OSError:time.sleep(.1)
  assert key,'Gateway readiness failed'
  import base64
  pub=subprocess.run(['openssl','pkey','-in',str(work/'state/signing.pem'),'-pubout','-outform','DER'],env=env,capture_output=True,check=True).stdout
  assert key==base64.b64encode(pub).decode()
  checkdir=work/'checker';(checkdir/'tests/fixtures/hacker-news').mkdir(parents=True);(checkdir/'server/web').mkdir(parents=True)
  download(PINS['checker'],checkdir/'tests/check_capture.mjs');download(PINS['checker_fixture'],checkdir/'tests/fixtures/hacker-news/response.http');shutil.copyfile(server/'web/verify.mjs',checkdir/'server/web/verify.mjs')
  report['sources']['checker']=digest(checkdir/'tests/check_capture.mjs');report['sources']['verifier_module']=digest(checkdir/'server/web/verify.mjs')
  for fn in [resources,lambda:prepared(original)]:thread=threading.Thread(target=fn,daemon=True);thread.start();threads.append(thread)
  stage='proof'
  env.update({'ABX_TLS_REFERENCE_OWNER':token,'ABX_PLUGINS_DIR':str(plugin/'plugins'),'ABXPKG_LIB_DIR':str(work/'lib'),'PERSONAS_DIR':str(work/'personas'),'TMP_DIR':str(work/'tmp'),'TMPDIR':str(work/'tmp'),'CHROME_BINARY':str(chrome),'NODE_BINARY':str(node),'CHROMEWEBSTORE_EXTENSIONS_DIR':str(extension_dir),'NODE_PATH':os.pathsep.join(str(work/'lib/pnpm/packages'/n/'node_modules') for n in ['chrome','abxbus']),'NODE_MODULES_DIR':str(work/'lib/pnpm/packages/chrome/node_modules'),'BROWSERS_BINARY':str(work/'lib/pnpm/packages/chrome/node_modules/.bin/browsers'),'ABXBUS_BINARY':str(work/'lib/pnpm/packages/abxbus/node_modules/abxbus/dist/cjs/index.js'),'CHROME_HEADLESS':'true','CHROME_SANDBOX':'true','CHROME_ARGS_EXTRA':'[]','TIMEOUT':'60','TLSNOTARY_ENABLED':'true','TLSNOTARY_TIMEOUT':'180','TLSNOTARY_MAX_RECV_BYTES':'131072','TLSNOTARY_MAX_SENT_BYTES':'4096','TLSNOTARY_VERIFIER_URL':endpoint,'TLSNOTARY_TRUSTED_KEY':key,'UV_OFFLINE':'true','npm_config_offline':'true'})
  env['PATH']=':'.join(str(work/'lib/pnpm/packages'/n/'node_modules/.bin') for n in ['chrome','abxbus'])+':'+env['PATH']
  consume(work);report['checks']['proof_started']=True
  capture=subprocess.Popen([str(py),'-m','abx_dl','dl','--plugins=chrome,tlsnotary','--no-install','--dir',str(work/'capture'),URL],env=env,cwd=work,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
  code=capture.wait(timeout=240);report['stages'].append({'stage':'proof','exit':code,'timeout':False,'error':''})
  for logfile in (work/'capture').glob('**/tlsnotary/*.stderr.log'):
   raw=logfile.read_text(errors='replace')[:1048576]
   if 'zk execution' in raw and 'connection is closed' in raw:report['failure_class']='zk_execution_closed'
   elif 'connection is closed' in raw:report['failure_class']='protocol_closed'
   elif code:report['failure_class']='other'
  assert code==0,'Proof producer failed'
  stage='verification';receipts=list((work/'capture').glob('**/tlsnotary/receipt.json'));assert len(receipts)==1,'No unique verified receipt'
  cmd([node,checkdir/'tests/check_capture.mjs',receipts[0].parent,key],timeout=30)
  assert report['checks']['prepared_complete'],'Prepared extension evidence missing'
  report['checks']['receipt_verified']=True;report['checks']['tamper_checks']=5
  assert all(any({'current','max','oom','oom_kill'}<=set(row[name]) for row in report['resources']) for name in ['gateway','verifier']),'Missing resource evidence'
  assert any(event['event']=='registration' for event in report['transport']) and any(event['event'] in {'relay_close','proxy_close','session_close'} for event in report['transport']),'Missing lifecycle evidence'
  report['outcome']='verified'
 except Exception as error:
  failed=True;report['outcome']='proof_failed' if report['checks']['proof_started'] else 'setup_failed'
  report['stages'].append({'stage':stage,'exit':None,'timeout':isinstance(error,subprocess.TimeoutExpired),'error':error.code if isinstance(error,sandbox_checks.SandboxCheckError) else ('timeout' if isinstance(error,subprocess.TimeoutExpired) else 'invariant_failed')})
 finally:
  stage='cleanup';stop.set();cleanup_errors=[]
  def attempt(fn):
   try:return fn()
   except Exception as error:cleanup_errors.append(type(error).__name__);return None
  if capture:
   def alive():
    try:os.killpg(capture.pid,0);return True
    except ProcessLookupError:return False
   if attempt(alive):
    attempt(lambda:os.killpg(capture.pid,signal.SIGINT));deadline=time.monotonic()+20
    while time.monotonic()<deadline and attempt(alive):time.sleep(.2)
    if attempt(alive):attempt(lambda:os.killpg(capture.pid,signal.SIGTERM));time.sleep(2)
   report['cleanup']['browser_stopped']=attempt(alive) is False;attempt(lambda:capture.wait(timeout=2))
  else:report['cleanup']['browser_stopped']=True
  for marker in work.glob('**/chrome.pid'):
   try:
    pid=int(marker.read_text().strip());assert pid>1;os.kill(pid,0);report['cleanup']['browser_stopped']=False
   except ProcessLookupError:pass
   except Exception:report['cleanup']['browser_stopped']=False
  if observer:attempt(observer.terminate);attempt(lambda:observer.wait(timeout=5))
  for thread in threads:
   attempt(lambda thread=thread:thread.join(timeout=12))
   if thread.is_alive():cleanup_errors.append('ObserverUnconfirmed')
  for name,cid in ids.items():
   def state(name=name,cid=cid):
    owned(cid);value=json.loads(cmd(DOCKER+['inspect',cid,'--format','{{json .State}}']))
    report['container_outcomes'].append({'service':name,'exit':value['ExitCode'],'oom':value['OOMKilled'],'running':value['Running']})
   attempt(state)
  if service_attempted:
   existing=attempt(lambda:cmd(DOCKER+['ps','-aq','--filter','label=com.docker.compose.project='+project]));owned_ids=[]
   for cid in (existing or '').splitlines():
    try:owned(cid);owned_ids.append(cid)
    except Exception:cleanup_errors.append('OwnershipUnverified')
   if existing is not None and len(existing.splitlines())==len(owned_ids):attempt(lambda:cmd(compose+['down','--timeout','35'],timeout=60))
   for cid in owned_ids:
    remaining=attempt(lambda cid=cid:cmd(DOCKER+['ps','-aq','--filter','id='+cid]))
    if remaining:
     try:owned(cid);cmd(DOCKER+['rm','-f',cid],timeout=45)
     except Exception:cleanup_errors.append('RemovalUnconfirmed')
  remaining=attempt(lambda:cmd(DOCKER+['ps','-aq','--filter','label=com.docker.compose.project='+project]));networks=attempt(lambda:cmd(DOCKER+['network','ls','-q','--filter','label=com.docker.compose.project='+project]))
  report['cleanup']['containers_removed']=remaining=='';report['cleanup']['networks_removed']=networks==''
  attempt(lambda:shutil.rmtree(work/'state'));report['cleanup']['key_removed']=not(work/'state').exists()
  attempt(lambda:shutil.rmtree(work));report['cleanup']['private_files_removed']=not work.exists()
  if cleanup_errors or not all(report['cleanup'].values()):report['outcome']='cleanup_failed';failed=True
  validate_report(report);(safe/'summary.json').write_text(json.dumps(report,indent=2))
  print(json.dumps({'outcome':report['outcome'],'proof_started':report['checks']['proof_started'],'cleaned':all(report['cleanup'].values())}))
 return 1 if failed else 0
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--safe',required=True);args=parser.parse_args();sys.exit(run(args.root,args.safe))
