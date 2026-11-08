"""Offline projection of the prior successful Linux downloader dependency closure.

No resolution, download or installation. Reject unfamiliar conditional edges rather
than approximating marker evaluation. This lock's selected closure has no markers.
"""
from pathlib import Path
import hashlib,json,re,tomllib
from urllib.parse import urlsplit

BASE_COMMIT='85b6f3335e89aad33d057b2f75e6a1a7ca50494b'
BASE_LOCK_SHA256='57fc95cbc9e8a4729e801b27c3cb24d1fc4c29b05a9d67278a712cfa1e883fd3'
ROOTS={'abx-dl':'1.13.320','abx-plugins':'1.13.655'}

def derive(lock_bytes):
 assert hashlib.sha256(lock_bytes).hexdigest()==BASE_LOCK_SHA256
 lock=tomllib.loads(lock_bytes.decode())
 by_name={}
 for package in lock['package']:by_name.setdefault(package['name'],[]).append(package)
 selected={};pending=list(ROOTS)
 while pending:
  name=pending.pop()
  if name in selected:continue
  choices=by_name[name];assert len(choices)==1,'Conditional package selection needs explicit review'
  package=choices[0]
  assert package['source']=={'registry':'https://pypi.org/simple'}
  assert not package.get('resolution-markers')
  assert re.fullmatch(r'[a-z0-9-]+',name) and re.fullmatch(r'[0-9A-Za-z.+!-]+',package['version'])
  if name in ROOTS:assert package['version']==ROOTS[name]
  for dependency in package.get('dependencies',[]):
   # The recorded default closure has no marker or extra edges, including for 3.13.
   assert set(dependency)=={'name'},'Conditional or extra dependency needs explicit review'
   pending.append(dependency['name'])
  selected[name]=package
 lines=['# Matching downloader closure, not full ArchiveBox environment equivalence.',
        '# Derived offline from ArchiveBox/ArchiveBox '+BASE_COMMIT+' uv.lock.',
        '# Target: CPython 3.13.18, Ubuntu 24.04 x86_64; wheel-only, no new resolution.']
 for name,package in sorted(selected.items()):
  wheels=package.get('wheels',[]);assert wheels,'Missing locked wheel artifacts'
  hashes=set()
  for wheel in wheels:
   url=urlsplit(wheel['url']);assert url.scheme=='https' and url.netloc=='files.pythonhosted.org' and url.path.endswith('.whl')
   assert re.fullmatch(r'sha256:[0-9a-f]{64}',wheel['hash'])
   hashes.add(wheel['hash'])
  lines.append(name+'=='+package['version']+' \\')
  hashes=sorted(hashes)
  lines.extend('    --hash='+value+(' \\' if index<len(hashes)-1 else '') for index,value in enumerate(hashes))
 return '\n'.join(lines)+'\n',selected

if __name__=='__main__':
 here=Path(__file__).resolve().parent
 expected,selected=derive((here/'baseline-uv.lock').read_bytes())
 assert (here/'requirements.txt').read_text()==expected,'Requirements differ from the prior lock closure'
 print(json.dumps({'packages':len(selected),'conditional_edges':0,'python':'3.13.18','matches_baseline_lock':True}))
