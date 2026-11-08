"""Idempotent external owned-state cleanup. Never emits private journal contents."""
import json,os,re,shutil,signal,subprocess,sys,time
from pathlib import Path
DOCKER=['docker','--host','unix:///var/run/docker.sock']
def persist_journal(path,value,*,create=False):
 path=Path(path)
 temporary=path.with_suffix('.pending')
 with temporary.open('x') as stream:
  os.chmod(temporary,0o600);json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
 if create:
  try:os.link(temporary,path)
  finally:temporary.unlink()
 else:os.replace(temporary,path)
 fd=os.open(path.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)

def mark_browser_invoked(path):
 value=json.loads(Path(path).read_text())
 assert type(value['browser_invoked']) is bool
 value['browser_invoked']=True;persist_journal(path,value)

def browser_cleanup_confirmed(invoked,candidates,inspection_uncertain,signal_failed,prior=None):
 assert type(invoked) is bool
 if not invoked:return True
 return not candidates and not inspection_uncertain and not signal_failed and prior is not False

def scan_processes(proc,token):
 result=[];uncertain=False
 try:entries=list(Path(proc).iterdir())
 except OSError:return [],True
 for entry in entries:
  if not entry.name.isdigit():continue
  try:
   if entry.stat().st_uid==os.getuid() and ('ABX_TLS_REFERENCE_OWNER='+token).encode() in (entry/'environ').read_bytes().split(b'\0'):result.append(int(entry.name))
  except (FileNotFoundError,ProcessLookupError):continue
  except OSError:uncertain=True
 return result,uncertain

def signal_owned(pid,sig):
 try:os.kill(pid,sig);return True
 except ProcessLookupError:return True
 except OSError:return False

def cleanup(root):
 root=Path(root).resolve();journal=root/'tls-ownership.json'
 if not journal.exists():return True
 value=json.loads(journal.read_text());assert set(value)=={'work','token','project','browser_invoked'}
 invoked=value['browser_invoked'];assert type(invoked) is bool
 token=value['token'];project=value['project'];work=Path(value['work'])
 assert re.fullmatch('[0-9a-f]{32}',token) and project=='abx-tls-'+token[:16]
 assert work.parent==root and work.name.startswith('tls-private-') and not work.is_symlink()
 env={'PATH':os.environ['PATH'],'HOME':str(root),'LANG':'C.UTF-8'}
 def cmd(args):
  result=subprocess.run(DOCKER+args,env=env,capture_output=True,text=True,timeout=60)
  assert result.returncode==0,'Owned cleanup command failed'
  return result.stdout.strip()
 errors=[];uncertain=False;signal_failed=False
 for sig in [signal.SIGINT,signal.SIGTERM,signal.SIGKILL]:
  candidates,unknown=scan_processes('/proc',token);uncertain |= unknown
  for pid in candidates:
   if not signal_owned(pid,sig):signal_failed=True
  candidates,unknown=scan_processes('/proc',token);uncertain |= unknown
  if not candidates:break
  time.sleep(2)
 candidates,unknown=scan_processes('/proc',token);uncertain |= unknown
 browser_stopped=browser_cleanup_confirmed(invoked,candidates,uncertain,signal_failed)
 if (invoked and uncertain) or signal_failed or candidates:errors.append('process_inspection')
 for kind,listing in [('container',['ps','-aq']),('network',['network','ls','-q'])]:
  try:identifiers=cmd(listing+['--filter','label=com.docker.compose.project='+project]).splitlines()
  except Exception:errors.append(kind);identifiers=[]
  for ident in identifiers:
   try:
    metadata=json.loads(cmd([kind,'inspect',ident]))[0]
    labels=metadata['Config']['Labels'] if kind=='container' else metadata['Labels']
    assert labels.get('com.docker.compose.project')==project and labels.get('io.archivebox.tls.reference-token')==token
    cmd(['rm','-f',ident] if kind=='container' else ['network','rm',ident])
   except Exception:errors.append(kind)
 results={}
 for name,listing in [('containers_removed',['ps','-aq']),('networks_removed',['network','ls','-q'])]:
  try:results[name]=not cmd(listing+['--filter','label=com.docker.compose.project='+project])
  except Exception:results[name]=False
 try:
  if work.exists():shutil.rmtree(work)
 except Exception:errors.append('files')
 results.update(key_removed=not(work/'state/signing.pem').exists(),private_files_removed=not work.exists(),browser_stopped=browser_stopped)
 summary=root/'tls-safe/summary.json'
 if summary.exists():
  from reference import validate_report
  report=validate_report(json.loads(summary.read_text()))
  report['checks']['browser_invoked']=invoked
  results['browser_stopped']=browser_cleanup_confirmed(invoked,candidates,uncertain,signal_failed,report['cleanup']['browser_stopped'])
  for key,ok in results.items():report['cleanup'][key]=ok
  if errors or not all(results.values()):report['outcome']='cleanup_failed'
  validate_report(report);summary.write_text(json.dumps(report,indent=2))
 return not errors and all(results.values())
if __name__=='__main__':
 try:ok=cleanup(sys.argv[1])
 except Exception:ok=False
 print('Owned cleanup complete' if ok else 'Owned cleanup unconfirmed');sys.exit(0 if ok else 1)
