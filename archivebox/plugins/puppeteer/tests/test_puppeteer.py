"""Integration tests for puppeteer plugin."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_plugin_dir,
    get_hook_script,
)


PLUGIN_DIR = get_plugin_dir(__file__)
CRAWL_HOOK = get_hook_script(PLUGIN_DIR, 'on_Crawl__*_puppeteer_install.py')
BINARY_HOOK = get_hook_script(PLUGIN_DIR, 'on_Binary__*_puppeteer_install.py')
NPM_BINARY_HOOK = PLUGIN_DIR.parent / 'npm' / 'on_Binary__10_npm_install.py'


def test_hook_scripts_exist():
    assert CRAWL_HOOK and CRAWL_HOOK.exists(), f"Hook not found: {CRAWL_HOOK}"
    assert BINARY_HOOK and BINARY_HOOK.exists(), f"Hook not found: {BINARY_HOOK}"


def test_crawl_hook_emits_puppeteer_binary():
    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        result = subprocess.run(
            [sys.executable, str(CRAWL_HOOK)],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, f"crawl hook failed: {result.stderr}"
        records = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith('{')]
        binaries = [r for r in records if r.get('type') == 'Binary' and r.get('name') == 'puppeteer']
        assert binaries, f"Expected Binary record for puppeteer, got: {records}"
        assert 'npm' in binaries[0].get('binproviders', ''), "puppeteer should be installable via npm provider"


@pytest.mark.skipif(shutil.which('npm') is None, reason='npm is required for puppeteer installation')
def test_puppeteer_installs_chromium():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        lib_dir = tmpdir / 'lib' / 'arm64-darwin'
        lib_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env['LIB_DIR'] = str(lib_dir)

        crawl_result = subprocess.run(
            [sys.executable, str(CRAWL_HOOK)],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert crawl_result.returncode == 0, f"crawl hook failed: {crawl_result.stderr}"
        crawl_records = [json.loads(line) for line in crawl_result.stdout.splitlines() if line.strip().startswith('{')]
        puppeteer_record = next(
            (r for r in crawl_records if r.get('type') == 'Binary' and r.get('name') == 'puppeteer'),
            None,
        )
        assert puppeteer_record, f"Expected puppeteer Binary record, got: {crawl_records}"

        npm_result = subprocess.run(
            [
                sys.executable,
                str(NPM_BINARY_HOOK),
                '--machine-id=test-machine',
                '--binary-id=test-puppeteer',
                '--name=puppeteer',
                f"--binproviders={puppeteer_record.get('binproviders', '*')}",
                '--overrides=' + json.dumps(puppeteer_record.get('overrides') or {}),
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert npm_result.returncode == 0, (
            "puppeteer npm install failed\n"
            f"stdout:\n{npm_result.stdout}\n"
            f"stderr:\n{npm_result.stderr}"
        )

        result = subprocess.run(
            [
                sys.executable,
                str(BINARY_HOOK),
                '--machine-id=test-machine',
                '--binary-id=test-binary',
                '--name=chromium',
                '--binproviders=puppeteer',
                '--overrides=' + json.dumps({'puppeteer': ['chromium@latest', '--install-deps']}),
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )

        assert result.returncode == 0, (
            "puppeteer binary hook failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

        records = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith('{')]
        binaries = [r for r in records if r.get('type') == 'Binary' and r.get('name') == 'chromium']
        assert binaries, f"Expected Binary record for chromium, got: {records}"
        abspath = binaries[0].get('abspath')
        assert abspath and Path(abspath).exists(), f"Chromium binary path invalid: {abspath}"
