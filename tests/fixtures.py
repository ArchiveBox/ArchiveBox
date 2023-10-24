import os
import subprocess

import pytest

@pytest.fixture
def process(tmp_path):
    os.chdir(tmp_path)
    process = subprocess.run(['archivebox', 'init'], capture_output=True)
    return process

@pytest.fixture
def disable_extractors_dict():
    env = os.environ.copy()
    env.update({
        "USE_WGET": "false",
        "USE_SINGLEFILE": "false",
        "USE_READABILITY": "false",
        "USE_MERCURY": "false",
        "SAVE_HTMLTOTEXT": "false",
        "SAVE_PDF": "false",
        "SAVE_SCREENSHOT": "false",
        "SAVE_DOM": "false",
        "SAVE_HEADERS": "false",
        "USE_GIT": "false",
        "SAVE_MEDIA": "false",
        "SAVE_ARCHIVE_DOT_ORG": "false"
    })
    return env
