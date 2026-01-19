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
INSTALL_SCRIPT = PLUGIN_DIR / 'on_Crawl__83_twocaptcha_install.js'
CONFIG_SCRIPT = PLUGIN_DIR / 'on_Crawl__95_twocaptcha_config.js'

TEST_URL = 'https://2captcha.com/demo/cloudflare-turnstile'


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
                # Wait for extensions.json to be written
                extensions_file = chrome_dir / 'extensions.json'
                for i in range(20):
                    if extensions_file.exists():
                        break
                    time.sleep(0.5)

                assert extensions_file.exists(), f"extensions.json not created. Chrome dir files: {list(chrome_dir.iterdir())}"

                exts = json.loads(extensions_file.read_text())
                assert any(e['name'] == 'twocaptcha' for e in exts), f"twocaptcha not loaded: {exts}"
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
                # Wait for extensions.json to be written
                extensions_file = chrome_dir / 'extensions.json'
                for i in range(20):
                    if extensions_file.exists():
                        break
                    time.sleep(0.5)
                assert extensions_file.exists(), f"extensions.json not created"

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
        """Extension attempts to solve CAPTCHA on demo page.

        CRITICAL: DO NOT SKIP OR DISABLE THIS TEST EVEN IF IT'S FLAKY!

        This test is INTENTIONALLY left enabled to expose the REAL, ACTUAL flakiness
        of the 2captcha service and demo page. The test failures you see here are NOT
        test bugs - they are ACCURATE representations of the real-world reliability
        of this CAPTCHA solving service.

        If this test is flaky, that's because 2captcha IS FLAKY in production.
        If this test fails intermittently, that's because 2captcha FAILS INTERMITTENTLY in production.

        NEVER EVER hide real flakiness by disabling tests or adding @pytest.mark.skip.
        Users NEED to see this failure rate to understand what they're getting into.

        When this test DOES pass, it confirms:
        - Extension loads and configures correctly
        - 2captcha API key is accepted
        - Extension can successfully auto-solve CAPTCHAs
        - The entire flow works end-to-end

        When it fails (as it often does):
        - Demo page has JavaScript errors (representing real-world broken sites)
        - Turnstile tokens expire before solving (representing real-world timing issues)
        - 2captcha service may be slow/down (representing real-world service issues)

        This is VALUABLE INFORMATION about the service. DO NOT HIDE IT.
        """
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
                # Wait for extensions.json to be written
                extensions_file = chrome_dir / 'extensions.json'
                for i in range(20):
                    if extensions_file.exists():
                        break
                    time.sleep(0.5)
                assert extensions_file.exists(), f"extensions.json not created"

                subprocess.run(['node', str(CONFIG_SCRIPT), '--url=x', '--snapshot-id=x'], env=env, timeout=30, capture_output=True)

                script = f'''
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');
(async () => {{
    const browser = await puppeteer.connect({{ browserWSEndpoint: '{cdp_url}' }});
    const page = await browser.newPage();

    // Capture console messages from the page (including extension messages)
    page.on('console', msg => {{
        const text = msg.text();
        if (text.includes('2captcha') || text.includes('turnstile') || text.includes('captcha')) {{
            console.error('[CONSOLE]', text);
        }}
    }});

    await page.setViewport({{ width: 1440, height: 900 }});
    console.error('[*] Loading {TEST_URL}...');
    await page.goto('{TEST_URL}', {{ waitUntil: 'networkidle2', timeout: 30000 }});

    // Wait for CAPTCHA iframe (minimal wait to avoid token expiration)
    console.error('[*] Waiting for CAPTCHA iframe...');
    await page.waitForSelector('iframe', {{ timeout: 30000 }});
    console.error('[*] CAPTCHA iframe found - extension should auto-solve now');

    // DON'T CLICK - extension should auto-solve since autoSolveTurnstile=True
    console.error('[*] Waiting for auto-solve (extension configured with autoSolveTurnstile=True)...');

    // Poll for data-state changes with debug output
    console.error('[*] Waiting for CAPTCHA to be solved (up to 150s)...');
    const start = Date.now();
    let solved = false;
    let lastState = null;

    while (!solved && (Date.now() - start) < 150000) {{
        const state = await page.evaluate(() => {{
            const solver = document.querySelector('.captcha-solver');
            return {{
                state: solver?.getAttribute('data-state'),
                text: solver?.textContent?.trim(),
                classList: solver?.className
            }};
        }});

        if (state.state !== lastState) {{
            const elapsed = Math.round((Date.now() - start) / 1000);
            console.error(`[*] State change at ${{elapsed}}s: "${{lastState}}" -> "${{state.state}}" (text: "${{state.text?.slice(0, 50)}}")`);
            lastState = state.state;
        }}

        if (state.state === 'solved') {{
            solved = true;
            const elapsed = Math.round((Date.now() - start) / 1000);
            console.error('[+] SOLVED in ' + elapsed + 's!');
            break;
        }}

        // Check every 2 seconds
        await new Promise(r => setTimeout(r, 2000));
    }}

    if (!solved) {{
        const elapsed = Math.round((Date.now() - start) / 1000);
        const finalState = await page.evaluate(() => {{
            const solver = document.querySelector('.captcha-solver');
            return {{
                state: solver?.getAttribute('data-state'),
                text: solver?.textContent?.trim(),
                html: solver?.outerHTML?.slice(0, 200)
            }};
        }});
        console.error(`[!] TIMEOUT after ${{elapsed}}s. Final state: ${{JSON.stringify(finalState)}}`);
        browser.disconnect();
        process.exit(1);
    }}

    const final = await page.evaluate(() => {{
        const solver = document.querySelector('.captcha-solver');
        return {{
            solved: true,
            state: solver?.getAttribute('data-state'),
            text: solver?.textContent?.trim()
        }};
    }});
    browser.disconnect();
    console.log(JSON.stringify(final));
}})();
'''
                (tmpdir / 's.js').write_text(script)
                print("\n[*] Solving CAPTCHA (this can take up to 150s for 2captcha API)...")
                r = subprocess.run(['node', str(tmpdir / 's.js')], env=env, timeout=200, capture_output=True, text=True)
                print(r.stderr)
                assert r.returncode == 0, f"Failed: {r.stderr}"

                final = json.loads([l for l in r.stdout.strip().split('\n') if l.startswith('{')][-1])
                assert final.get('solved'), f"Not solved: {final}"
                assert final.get('state') == 'solved', f"State not 'solved': {final}"
                print(f"[+] SUCCESS! CAPTCHA solved: {final.get('text','')[:50]}")
            finally:
                kill_chrome(process, chrome_dir)


if __name__ == '__main__':
    pytest.main([__file__, '-xvs'])
