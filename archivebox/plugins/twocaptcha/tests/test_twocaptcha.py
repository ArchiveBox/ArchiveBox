"""
Integration tests for twocaptcha plugin

Run with: TWOCAPTCHA_API_KEY=your_key pytest archivebox/plugins/twocaptcha/tests/ -xvs

NOTE: Chrome 137+ removed --load-extension support, so these tests MUST use Chromium.
"""

import json
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    setup_test_env,
    launch_chromium_session,
    kill_chromium_session,
    CHROME_LAUNCH_HOOK,
    PLUGINS_ROOT,
)


PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_SCRIPT = PLUGIN_DIR / 'on_Crawl__20_install_twocaptcha_extension.js'
CONFIG_SCRIPT = PLUGIN_DIR / 'on_Crawl__25_configure_twocaptcha_extension_options.js'

TEST_URL = 'https://2captcha.com/demo/recaptcha-v2'


# Alias for backward compatibility with existing test names
launch_chrome = launch_chromium_session
kill_chrome = kill_chromium_session


class TestTwoCaptcha:
    """Integration tests requiring TWOCAPTCHA_API_KEY."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.api_key = os.environ.get('TWOCAPTCHA_API_KEY') or os.environ.get('API_KEY_2CAPTCHA')
        if not self.api_key:
            pytest.skip("TWOCAPTCHA_API_KEY required")

    def test_install_and_load(self):
        """Extension installs and loads in Chromium."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            env = setup_test_env(tmpdir)
            env['TWOCAPTCHA_API_KEY'] = self.api_key

            # Install
            result = subprocess.run(['node', str(INSTALL_SCRIPT)], env=env, timeout=120, capture_output=True, text=True)
            assert result.returncode == 0, f"Install failed: {result.stderr}"

            cache = Path(env['CHROME_EXTENSIONS_DIR']) / 'twocaptcha.extension.json'
            assert cache.exists()
            data = json.loads(cache.read_text())
            assert data['webstore_id'] == 'ifibfemgeogfhoebkmokieepdoobkbpo'

            # Launch Chromium in crawls directory
            crawl_id = 'test'
            crawl_dir = Path(env['CRAWLS_DIR']) / crawl_id
            chrome_dir = crawl_dir / 'chrome'
            env['CRAWL_OUTPUT_DIR'] = str(crawl_dir)
            process, cdp_url = launch_chrome(env, chrome_dir, crawl_id)

            try:
                exts = json.loads((chrome_dir / 'extensions.json').read_text())
                assert any(e['name'] == 'twocaptcha' for e in exts), f"Not loaded: {exts}"
                print(f"[+] Extension loaded: id={next(e['id'] for e in exts if e['name']=='twocaptcha')}")
            finally:
                kill_chrome(process, chrome_dir)

    def test_config_applied(self):
        """Configuration is applied to extension and verified via Config.getAll()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            env = setup_test_env(tmpdir)
            env['TWOCAPTCHA_API_KEY'] = self.api_key
            env['TWOCAPTCHA_RETRY_COUNT'] = '5'
            env['TWOCAPTCHA_RETRY_DELAY'] = '10'

            subprocess.run(['node', str(INSTALL_SCRIPT)], env=env, timeout=120, capture_output=True)

            # Launch Chromium in crawls directory
            crawl_id = 'cfg'
            crawl_dir = Path(env['CRAWLS_DIR']) / crawl_id
            chrome_dir = crawl_dir / 'chrome'
            env['CRAWL_OUTPUT_DIR'] = str(crawl_dir)
            process, cdp_url = launch_chrome(env, chrome_dir, crawl_id)

            try:
                result = subprocess.run(
                    ['node', str(CONFIG_SCRIPT), '--url=https://example.com', '--snapshot-id=test'],
                    env=env, timeout=30, capture_output=True, text=True
                )
                assert result.returncode == 0, f"Config failed: {result.stderr}"
                assert (chrome_dir / '.twocaptcha_configured').exists()

                # Verify config via options.html and Config.getAll()
                # Get the actual extension ID from the config marker (Chrome computes IDs differently)
                config_marker = json.loads((chrome_dir / '.twocaptcha_configured').read_text())
                ext_id = config_marker['extensionId']
                script = f'''
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');
(async () => {{
    const browser = await puppeteer.connect({{ browserWSEndpoint: '{cdp_url}' }});

    // Load options.html and use Config.getAll() to verify
    const optionsUrl = 'chrome-extension://{ext_id}/options/options.html';
    const page = await browser.newPage();
    console.error('[*] Loading options page:', optionsUrl);

    // Navigate - catch error but continue since page may still load
    try {{
        await page.goto(optionsUrl, {{ waitUntil: 'networkidle0', timeout: 10000 }});
    }} catch (e) {{
        console.error('[*] Navigation threw error (may still work):', e.message);
    }}

    // Wait for page to settle
    await new Promise(r => setTimeout(r, 2000));
    console.error('[*] Current URL:', page.url());

    // Wait for Config object to be available
    await page.waitForFunction(() => typeof Config !== 'undefined', {{ timeout: 5000 }});

    // Call Config.getAll() - the extension's own API (returns a Promise)
    const cfg = await page.evaluate(async () => await Config.getAll());
    console.error('[*] Config.getAll() returned:', JSON.stringify(cfg));

    await page.close();
    browser.disconnect();
    console.log(JSON.stringify(cfg));
}})();
'''
                (tmpdir / 'v.js').write_text(script)
                r = subprocess.run(['node', str(tmpdir / 'v.js')], env=env, timeout=30, capture_output=True, text=True)
                print(r.stderr)
                assert r.returncode == 0, f"Verify failed: {r.stderr}"

                cfg = json.loads(r.stdout.strip().split('\n')[-1])
                print(f"[*] Config from extension: {json.dumps(cfg, indent=2)}")

                # Verify all the fields we care about
                assert cfg.get('apiKey') == self.api_key or cfg.get('api_key') == self.api_key, f"API key not set: {cfg}"
                assert cfg.get('isPluginEnabled') == True, f"Plugin not enabled: {cfg}"
                assert cfg.get('repeatOnErrorTimes') == 5, f"Retry count wrong: {cfg}"
                assert cfg.get('repeatOnErrorDelay') == 10, f"Retry delay wrong: {cfg}"
                assert cfg.get('autoSolveRecaptchaV2') == True, f"autoSolveRecaptchaV2 not enabled: {cfg}"
                assert cfg.get('autoSolveRecaptchaV3') == True, f"autoSolveRecaptchaV3 not enabled: {cfg}"
                assert cfg.get('autoSolveTurnstile') == True, f"autoSolveTurnstile not enabled: {cfg}"
                assert cfg.get('enabledForRecaptchaV2') == True, f"enabledForRecaptchaV2 not enabled: {cfg}"

                print(f"[+] Config verified via Config.getAll()!")
            finally:
                kill_chrome(process, chrome_dir)

    def test_solves_recaptcha(self):
        """Extension solves reCAPTCHA on demo page."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            env = setup_test_env(tmpdir)
            env['TWOCAPTCHA_API_KEY'] = self.api_key

            subprocess.run(['node', str(INSTALL_SCRIPT)], env=env, timeout=120, capture_output=True)

            # Launch Chromium in crawls directory
            crawl_id = 'solve'
            crawl_dir = Path(env['CRAWLS_DIR']) / crawl_id
            chrome_dir = crawl_dir / 'chrome'
            env['CRAWL_OUTPUT_DIR'] = str(crawl_dir)
            process, cdp_url = launch_chrome(env, chrome_dir, crawl_id)

            try:
                subprocess.run(['node', str(CONFIG_SCRIPT), '--url=x', '--snapshot-id=x'], env=env, timeout=30, capture_output=True)

                script = f'''
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');
(async () => {{
    const browser = await puppeteer.connect({{ browserWSEndpoint: '{cdp_url}' }});
    const page = await browser.newPage();
    await page.setViewport({{ width: 1440, height: 900 }});
    console.error('[*] Loading {TEST_URL}...');
    await page.goto('{TEST_URL}', {{ waitUntil: 'networkidle2', timeout: 30000 }});
    await new Promise(r => setTimeout(r, 3000));

    const start = Date.now();
    const maxWait = 90000;

    while (Date.now() - start < maxWait) {{
        const state = await page.evaluate(() => {{
            const resp = document.querySelector('textarea[name="g-recaptcha-response"]');
            const solver = document.querySelector('.captcha-solver');
            return {{
                solved: resp ? resp.value.length > 0 : false,
                state: solver?.getAttribute('data-state'),
                text: solver?.textContent?.trim() || ''
            }};
        }});
        const sec = Math.round((Date.now() - start) / 1000);
        console.error('[*] ' + sec + 's state=' + state.state + ' solved=' + state.solved + ' text=' + state.text.slice(0,30));
        if (state.solved) {{ console.error('[+] SOLVED!'); break; }}
        if (state.state === 'error') {{ console.error('[!] ERROR'); break; }}
        await new Promise(r => setTimeout(r, 2000));
    }}

    const final = await page.evaluate(() => {{
        const resp = document.querySelector('textarea[name="g-recaptcha-response"]');
        return {{ solved: resp ? resp.value.length > 0 : false, preview: resp?.value?.slice(0,50) || '' }};
    }});
    browser.disconnect();
    console.log(JSON.stringify(final));
}})();
'''
                (tmpdir / 's.js').write_text(script)
                print("\n[*] Solving CAPTCHA (10-60s)...")
                r = subprocess.run(['node', str(tmpdir / 's.js')], env=env, timeout=120, capture_output=True, text=True)
                print(r.stderr)
                assert r.returncode == 0, f"Failed: {r.stderr}"

                final = json.loads([l for l in r.stdout.strip().split('\n') if l.startswith('{')][-1])
                assert final.get('solved'), f"Not solved: {final}"
                print(f"[+] SOLVED! {final.get('preview','')[:30]}...")
            finally:
                kill_chrome(process, chrome_dir)


if __name__ == '__main__':
    pytest.main([__file__, '-xvs'])
