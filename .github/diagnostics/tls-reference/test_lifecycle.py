import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from cleanup import persist_journal,mark_browser_invoked,browser_cleanup_confirmed
class Lifecycle(unittest.TestCase):
 def journal(self,root):
  path=Path(root)/'ownership.json';persist_journal(path,{'work':str(Path(root)/'tls-private-test'),'token':'a'*32,'project':'abx-tls-'+('a'*16),'browser_invoked':False},create=True);return path
 def test_before_browser_failure(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.journal(d);self.assertFalse(json.loads(p.read_text())['browser_invoked']);self.assertTrue(browser_cleanup_confirmed(False,[],True,False))
 def test_invocation_failure_remains_uncertain(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.journal(d);mark_browser_invoked(p);self.assertTrue(json.loads(p.read_text())['browser_invoked']);self.assertFalse(browser_cleanup_confirmed(True,[],True,False))
 def test_success_and_prior_uncertainty(self):
  self.assertTrue(browser_cleanup_confirmed(True,[],False,False,True))
  self.assertFalse(browser_cleanup_confirmed(True,[],False,False,False))
  self.assertFalse(browser_cleanup_confirmed(True,[123],False,False))
  self.assertFalse(browser_cleanup_confirmed(True,[],False,True))
 def test_interrupted_marker_is_durable(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.journal(d)
   result=subprocess.run([sys.executable,'-c','from cleanup import mark_browser_invoked;import os,sys;mark_browser_invoked(sys.argv[1]);os._exit(7)',str(p)],cwd=Path(__file__).parent,env={'PATH':os.environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'})
   self.assertEqual(result.returncode,7);self.assertTrue(json.loads(p.read_text())['browser_invoked']);self.assertFalse(browser_cleanup_confirmed(True,[],True,False))
 def test_one_journal_only(self):
  with tempfile.TemporaryDirectory() as d:
   self.journal(d)
   with self.assertRaises(FileExistsError):self.journal(d)
 def test_marker_precedes_all_chrome_calls(self):
  text=(Path(__file__).parent/'reference.py').read_text();marker=text.index('mark_browser_invoked(journal);');self.assertLess(marker,text.index("cmd([chrome,'--version'])"));self.assertLess(marker,text.index("page=cmd([chrome,"));self.assertIn("'browser_invoked':False",text)
if __name__=='__main__':unittest.main()
