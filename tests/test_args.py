import subprocess

from .fixtures import *

def test_depth_flag_is_accepted(tmp_path, process):
    arg_process = subprocess.run(["archivebox", "add", "https://example.com", "--depth=0"], capture_output=True)
    assert 'unrecognized arguments: --depth' not in arg_process.stderr.decode('utf-8')