import os
import subprocess

import pytest

@pytest.fixture
def process(tmp_path):
    os.chdir(tmp_path)
    process = subprocess.run(['archivebox', 'init'], capture_output=True)
    return process