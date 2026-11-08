"""Pure stock-helper metadata checks; never configures or launches a sandbox."""
import re
from pathlib import PurePosixPath
HELPER='/opt/google/chrome/chrome-sandbox'
STAGES={'sandbox_helper_stat','sandbox_helper_owner','sandbox_helper_checksum','sandbox_helper_version','sandbox_probe','sandbox_page'}
ERRORS={'helper_not_root','helper_wrong_mode','helper_owner_mismatch','helper_checksum_missing','helper_checksum_ambiguous','helper_checksum_mismatch','helper_metadata_invalid','sandbox_page_inadequate'}
class SandboxCheckError(Exception):
 def __init__(self,code):
  assert code in ERRORS
  self.code=code;super().__init__(code)
def require(condition,code):
 if not condition:raise SandboxCheckError(code)
def validate_stat(uid,mode):
 require(uid==0,'helper_not_root');require(mode==0o4755,'helper_wrong_mode')
def package_owner(output):
 lines=output.splitlines();require(len(lines)==1,'helper_owner_mismatch')
 owner,separator,path=lines[0].partition(': ')
 require(separator and path==HELPER and re.fullmatch(r'google-chrome-stable(?::amd64)?',owner),'helper_owner_mismatch')
 return owner
def checksum_match(metadata,actual):
 matches=[]
 for line in metadata.splitlines():
  m=re.fullmatch(r'([0-9a-fA-F]{32})  ([^\r\n]+)',line)
  require(m is not None,'helper_metadata_invalid')
  name=m[2]
  require(not name.startswith(('/', './')) and '..' not in PurePosixPath(name).parts and name==name.strip(),'helper_metadata_invalid')
  if name==HELPER.removeprefix('/'):matches.append(m[1].lower())
 require(bool(matches),'helper_checksum_missing');require(len(matches)==1,'helper_checksum_ambiguous')
 require(matches[0]==actual.lower(),'helper_checksum_mismatch')
def probe_args(chrome,profile):
 return [chrome,'--headless','--no-first-run','--no-default-browser-check','--user-data-dir='+str(profile),'--allow-chrome-scheme-url','--dump-dom','chrome://sandbox']
def validate_page(page):require('You are adequately sandboxed' in page,'sandbox_page_inadequate')
