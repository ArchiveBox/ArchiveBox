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
        "SAVE_WGET": "false",
        "SAVE_SINGLEFILE": "false",
        "SAVE_READABILITY": "false",
        "SAVE_MERCURY": "false",
        "SAVE_HTMLTOTEXT": "false",
        "SAVE_PDF": "false",
        "SAVE_SCREENSHOT": "false",
        "SAVE_DOM": "false",
        "SAVE_HEADERS": "false",
        "SAVE_GIT": "false",
        "SAVE_YTDLP": "false",
        "SAVE_ARCHIVEDOTORG": "false",
        "SAVE_TITLE": "false",
        "SAVE_FAVICON": "false",
    })
    return env
