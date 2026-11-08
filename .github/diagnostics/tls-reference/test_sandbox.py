import hashlib,json,tempfile,unittest
from pathlib import Path
import sandbox_checks as s
from cleanup import persist_journal,mark_version_state,mark_browser_invoked,needs_browser_cleanup
class Sandbox(unittest.TestCase):
 def expect_failure(self,code,fn,*args):
  with self.assertRaises(s.SandboxCheckError) as caught:fn(*args)
  self.assertEqual(caught.exception.code,code)
 def test_stat(self):
  s.validate_stat(0,0o4755);self.expect_failure('helper_not_root',s.validate_stat,1001,0o4755);self.expect_failure('helper_wrong_mode',s.validate_stat,0,0o755)
 def test_ownership(self):
  for owner in ['google-chrome-stable','google-chrome-stable:amd64']:self.assertEqual(s.package_owner(owner+': '+s.HELPER),owner)
  for value in ['other: '+s.HELPER,'google-chrome-stable: /wrong','google-chrome-stable, other: '+s.HELPER,'diversion by google-chrome-stable from: '+s.HELPER,'google-chrome-stable: '+s.HELPER+'\nother: '+s.HELPER]:self.expect_failure('helper_owner_mismatch',s.package_owner,value)
 def test_checksum_formats(self):
  h=hashlib.md5(b'public test helper bytes').hexdigest()
  s.checksum_match(h.upper()+'  '+s.HELPER.lstrip('/'),h)
 def test_checksum_failures(self):
  h='a'*32;line=h+'  '+s.HELPER.lstrip('/')
  self.expect_failure('helper_checksum_missing',s.checksum_match,h+'  usr/bin/other',h)
  self.expect_failure('helper_checksum_ambiguous',s.checksum_match,line+'\n'+line,h)
  self.expect_failure('helper_checksum_mismatch',s.checksum_match,line,'b'*32)
  for bad in [h+' '+s.HELPER.lstrip('/'),h+'\t'+s.HELPER.lstrip('/'),h+'  ./'+s.HELPER.lstrip('/'),h+'  '+s.HELPER,'not a checksum',h+'  ../opt/google/chrome/chrome-sandbox',line+' ']:self.expect_failure('helper_metadata_invalid',s.checksum_match,bad,h)
 def test_page_and_flags(self):
  s.validate_page('<p>You are adequately sandboxed.</p>');self.expect_failure('sandbox_page_inadequate',s.validate_page,'<html></html>')
  args=s.probe_args('/public/chrome','/public/profile');self.assertIn('--allow-chrome-scheme-url',args);self.assertNotIn('--no-sandbox',args);self.assertEqual(args[-1],'chrome://sandbox')
  source=(Path(__file__).parent/'reference.py').read_text();self.assertNotIn('--allow-chrome-scheme-url',source);self.assertIn("'CHROME_ARGS_EXTRA':'[]'",source)
 def test_version_and_probe_lifecycle(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'journal';v={'work':d,'token':'a'*32,'project':'abx-tls-'+('a'*16),'browser_invoked':False,'chrome_version_invoked':False,'chrome_version_completed':False};persist_journal(p,v,create=True)
   self.assertFalse(needs_browser_cleanup(v));mark_version_state(p,False);self.assertTrue(needs_browser_cleanup(json.loads(p.read_text())))
   mark_version_state(p,True);self.assertFalse(needs_browser_cleanup(json.loads(p.read_text())))
   mark_browser_invoked(p);self.assertTrue(needs_browser_cleanup(json.loads(p.read_text())))
if __name__=='__main__':unittest.main()
