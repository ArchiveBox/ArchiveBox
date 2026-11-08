"""Pure tests for the prior lock's closed default downloader dependencies."""
import hashlib,json,re,tomllib,unittest
from pathlib import Path
import derive_requirements as d
import reference as r
HERE=Path(__file__).resolve().parent

def compatible_wheels(package):
 result=[]
 for wheel in package['wheels']:
  filename=wheel['url'].rsplit('/',1)[-1]
  _,python,abi,platform=filename[:-4].rsplit('-',3)
  tags=python.split('.')
  python_ok=(abi=='none' and ('py3' in tags or 'cp313' in tags)) or (abi=='cp313' and 'cp313' in tags) or (abi=='abi3' and any(re.fullmatch(r'cp3[0-9]+',tag) and 2<=int(tag[3:])<=13 for tag in tags))
  platforms=platform.split('.')
  # Ubuntu 24.04 x86_64 / glibc 2.39. Reject musl, macOS, free-threaded ABIs.
  platform_ok=any(tag=='any' or tag in {'manylinux1_x86_64','manylinux2010_x86_64','manylinux2014_x86_64'} or (re.fullmatch(r'manylinux_2_[0-9]+_x86_64',tag) and int(tag.split('_')[2])<=39) for tag in platforms)
  if python_ok and platform_ok:result.append({'filename':filename,'hash':wheel['hash'],'python_tag':python,'abi_tag':abi,'platform_tag':platform})
 return result

class Baseline(unittest.TestCase):
 def test_closed_exact_requirements(self):
  raw=(HERE/'baseline-uv.lock').read_bytes();lock=tomllib.loads(raw.decode());expected,selected=d.derive(raw)
  self.assertEqual(hashlib.sha256(raw).hexdigest(),d.BASE_LOCK_SHA256)
  self.assertEqual(hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),'85bc2c498e378039015938867b676f9b482ef5be')
  self.assertEqual(lock['requires-python'],'>=3.13')
  by_name={p['name']:p for p in lock['package']};reachable=set(d.ROOTS)
  while True:
   expanded=reachable|{edge['name'] for name in reachable for edge in by_name[name].get('dependencies',[])}
   if expanded==reachable:break
   reachable=expanded
  actual={}
  for block in (HERE/'requirements.txt').read_text().replace('\\\n','').splitlines():
   if not block or block.startswith('#'):continue
   name,version=re.match(r'([a-z0-9-]+)==([^ ]+)',block).groups()
   self.assertNotIn(name,actual);actual[name]=(version,set(re.findall(r'--hash=(sha256:[0-9a-f]{64})',block)))
  self.assertEqual(set(actual),reachable);self.assertEqual(set(selected),reachable);self.assertEqual(len(reachable),28)
  self.assertEqual((HERE/'requirements.txt').read_text(),expected)
  for name,(version,hashes) in actual.items():
   package=by_name[name];self.assertEqual(version,package['version']);self.assertEqual(hashes,{w['hash'] for w in package['wheels']})
   for dependency in package.get('dependencies',[]):self.assertEqual(set(dependency),{'name'})
   self.assertTrue(compatible_wheels(package),name)
   self.assertNotIn('requires-python',package) # Per-wheel metadata absent; do not claim it was inspected.
 def test_provenance_and_frozen_runtime(self):
  provenance=json.loads((HERE/'baseline-provenance.json').read_text())
  _,selected=d.derive((HERE/'baseline-uv.lock').read_bytes())
  self.assertEqual(provenance['compatible_wheels'],{name:compatible_wheels(package) for name,package in sorted(selected.items())})
  self.assertEqual(r.PINS['python'],'3.13.18');self.assertEqual(r.PINS['uv'],'0.13.5')
  self.assertIn("python-version: '3.13.18'",(HERE.parents[1]/'workflows/diagnose-canva.yml').read_text())
 def test_altered_source_rejected(self):
  with self.assertRaises(AssertionError):d.derive((HERE/'baseline-uv.lock').read_bytes()+b'\n')

if __name__=='__main__':unittest.main()
