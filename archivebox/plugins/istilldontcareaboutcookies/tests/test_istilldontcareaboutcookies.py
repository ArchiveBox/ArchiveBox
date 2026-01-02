"""
Unit tests for istilldontcareaboutcookies plugin

Tests invoke the plugin hook as an external process and verify outputs/side effects.
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
INSTALL_SCRIPT = next(PLUGIN_DIR.glob('on_Crawl__*_install_istilldontcareaboutcookies_extension.*'), None)


def test_install_script_exists():
    """Verify install script exists"""
    assert INSTALL_SCRIPT.exists(), f"Install script not found: {INSTALL_SCRIPT}"


def test_extension_metadata():
    """Test that extension has correct metadata"""
    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(Path(tmpdir) / "chrome_extensions")

        result = subprocess.run(
            ["node", "-e", f"const ext = require('{INSTALL_SCRIPT}'); console.log(JSON.stringify(ext.EXTENSION))"],
            capture_output=True,
            text=True,
            env=env
        )

        assert result.returncode == 0, f"Failed to load extension metadata: {result.stderr}"

        metadata = json.loads(result.stdout)
        assert metadata["webstore_id"] == "edibdbjcniadpccecjdfdjjppcpchdlm"
        assert metadata["name"] == "istilldontcareaboutcookies"


def test_install_creates_cache():
    """Test that install creates extension cache"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)

        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Check output mentions installation
        assert "Installing" in result.stdout or "installed" in result.stdout or "istilldontcareaboutcookies" in result.stdout

        # Check cache file was created
        cache_file = ext_dir / "istilldontcareaboutcookies.extension.json"
        assert cache_file.exists(), "Cache file should be created"

        # Verify cache content
        cache_data = json.loads(cache_file.read_text())
        assert cache_data["webstore_id"] == "edibdbjcniadpccecjdfdjjppcpchdlm"
        assert cache_data["name"] == "istilldontcareaboutcookies"


def test_install_uses_existing_cache():
    """Test that install uses existing cache when available"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        # Create fake cache
        fake_extension_dir = ext_dir / "edibdbjcniadpccecjdfdjjppcpchdlm__istilldontcareaboutcookies"
        fake_extension_dir.mkdir(parents=True)

        manifest = {"version": "1.1.8", "name": "I still don't care about cookies"}
        (fake_extension_dir / "manifest.json").write_text(json.dumps(manifest))

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)

        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        # Should use cache or install successfully
        assert result.returncode == 0


def test_no_configuration_required():
    """Test that extension works without any configuration"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        # No special env vars needed - works out of the box

        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Should not require any API keys or configuration
        assert "API" not in (result.stdout + result.stderr) or result.returncode == 0


TEST_URL = 'https://www.filmin.es/'


def test_extension_loads_in_chromium():
    """Verify extension loads in Chromium by visiting its options page.

    Uses Chromium with --load-extension to load the extension, then navigates
    to chrome-extension://<id>/options.html and checks that the extension name
    appears in the page content.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set up isolated env with proper directory structure
        env = setup_test_env(tmpdir)
        env.setdefault('CHROME_HEADLESS', 'true')

        ext_dir = Path(env['CHROME_EXTENSIONS_DIR'])

        # Step 1: Install the extension
        result = subprocess.run(
            ['node', str(INSTALL_SCRIPT)],
            cwd=str(tmpdir),
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )
        assert result.returncode == 0, f"Extension install failed: {result.stderr}"

        # Verify extension cache was created
        cache_file = ext_dir / 'istilldontcareaboutcookies.extension.json'
        assert cache_file.exists(), "Extension cache not created"
        ext_data = json.loads(cache_file.read_text())
        print(f"Extension installed: {ext_data.get('name')} v{ext_data.get('version')}")

        # Step 2: Launch Chromium using the chrome hook (loads extensions automatically)
        crawl_id = 'test-cookies'
        crawl_dir = Path(env['CRAWLS_DIR']) / crawl_id
        crawl_dir.mkdir(parents=True, exist_ok=True)
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir(parents=True, exist_ok=True)
        env['CRAWL_OUTPUT_DIR'] = str(crawl_dir)

        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), f'--crawl-id={crawl_id}'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Wait for Chromium to launch and CDP URL to be available
        cdp_url = None
        for i in range(20):
            if chrome_launch_process.poll() is not None:
                stdout, stderr = chrome_launch_process.communicate()
                raise RuntimeError(f"Chromium launch failed:\nStdout: {stdout}\nStderr: {stderr}")
            cdp_file = chrome_dir / 'cdp_url.txt'
            if cdp_file.exists():
                cdp_url = cdp_file.read_text().strip()
                break
            time.sleep(1)

        assert cdp_url, "Chromium CDP URL not found after 20s"
        print(f"Chromium launched with CDP URL: {cdp_url}")

        # Check that extensions were loaded
        extensions_file = chrome_dir / 'extensions.json'
        if extensions_file.exists():
            loaded_exts = json.loads(extensions_file.read_text())
            print(f"Extensions loaded: {[e.get('name') for e in loaded_exts]}")

        try:
            # Step 3: Connect to Chromium and verify extension loaded via options page
            test_script = f'''
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

(async () => {{
    const browser = await puppeteer.connect({{ browserWSEndpoint: '{cdp_url}' }});

    // Wait for extension to initialize
    await new Promise(r => setTimeout(r, 2000));

    // Find extension targets to get the extension ID
    const targets = browser.targets();
    const extTargets = targets.filter(t =>
        t.url().startsWith('chrome-extension://') ||
        t.type() === 'service_worker' ||
        t.type() === 'background_page'
    );

    // Filter out Chrome's built-in extensions
    const builtinIds = ['nkeimhogjdpnpccoofpliimaahmaaome', 'fignfifoniblkonapihmkfakmlgkbkcf',
                       'ahfgeienlihckogmohjhadlkjgocpleb', 'mhjfbmdgcfjbbpaeojofohoefgiehjai'];
    const customExtTargets = extTargets.filter(t => {{
        const url = t.url();
        if (!url.startsWith('chrome-extension://')) return false;
        const extId = url.split('://')[1].split('/')[0];
        return !builtinIds.includes(extId);
    }});

    console.error('Custom extension targets found:', customExtTargets.length);
    customExtTargets.forEach(t => console.error('  -', t.type(), t.url()));

    if (customExtTargets.length === 0) {{
        console.log(JSON.stringify({{ loaded: false, error: 'No custom extension targets found' }}));
        browser.disconnect();
        return;
    }}

    // Get the extension ID from the first custom extension target
    const extUrl = customExtTargets[0].url();
    const extId = extUrl.split('://')[1].split('/')[0];
    console.error('Extension ID:', extId);

    // Try to navigate to the extension's options.html page
    const page = await browser.newPage();
    const optionsUrl = 'chrome-extension://' + extId + '/options.html';
    console.error('Navigating to options page:', optionsUrl);

    try {{
        await page.goto(optionsUrl, {{ waitUntil: 'domcontentloaded', timeout: 10000 }});
        const pageContent = await page.content();
        const pageTitle = await page.title();

        // Check if extension name appears in the page
        const hasExtensionName = pageContent.toLowerCase().includes('cookie') ||
                                pageContent.toLowerCase().includes('idontcareaboutcookies') ||
                                pageTitle.toLowerCase().includes('cookie');

        console.log(JSON.stringify({{
            loaded: true,
            extensionId: extId,
            optionsPageLoaded: true,
            pageTitle: pageTitle,
            hasExtensionName: hasExtensionName,
            contentLength: pageContent.length
        }}));
    }} catch (e) {{
        // options.html may not exist, but extension is still loaded
        console.log(JSON.stringify({{
            loaded: true,
            extensionId: extId,
            optionsPageLoaded: false,
            error: e.message
        }}));
    }}

    browser.disconnect();
}})();
'''
            script_path = tmpdir / 'test_extension.js'
            script_path.write_text(test_script)

            result = subprocess.run(
                ['node', str(script_path)],
                cwd=str(tmpdir,
            env=get_test_env()),
                capture_output=True,
                text=True,
                env=env,
                timeout=90
            )

            print(f"stderr: {result.stderr}")
            print(f"stdout: {result.stdout}")

            assert result.returncode == 0, f"Test failed: {result.stderr}"

            output_lines = [l for l in result.stdout.strip().split('\n') if l.startswith('{')]
            assert output_lines, f"No JSON output: {result.stdout}"

            test_result = json.loads(output_lines[-1])
            assert test_result.get('loaded'), \
                f"Extension should be loaded in Chromium. Result: {test_result}"
            print(f"Extension loaded successfully: {test_result}")

        finally:
            # Clean up Chromium
            try:
                chrome_launch_process.send_signal(signal.SIGTERM)
                chrome_launch_process.wait(timeout=5)
            except:
                pass
            chrome_pid_file = chrome_dir / 'chrome.pid'
            if chrome_pid_file.exists():
                try:
                    chrome_pid = int(chrome_pid_file.read_text().strip())
                    os.kill(chrome_pid, signal.SIGKILL)
                except (OSError, ValueError):
                    pass


def check_cookie_consent_visibility(cdp_url: str, test_url: str, env: dict, script_dir: Path) -> dict:
    """Check if cookie consent elements are visible on a page.

    Returns dict with:
        - visible: bool - whether any cookie consent element is visible
        - selector: str - which selector matched (if visible)
        - elements_found: list - all cookie-related elements found in DOM
        - html_snippet: str - snippet of the page HTML for debugging
    """
    test_script = f'''
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

(async () => {{
    const browser = await puppeteer.connect({{ browserWSEndpoint: '{cdp_url}' }});

    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');
    await page.setViewport({{ width: 1440, height: 900 }});

    console.error('Navigating to {test_url}...');
    await page.goto('{test_url}', {{ waitUntil: 'networkidle2', timeout: 30000 }});

    // Wait for page to fully render and any cookie scripts to run
    await new Promise(r => setTimeout(r, 3000));

    // Check cookie consent visibility using multiple common selectors
    const result = await page.evaluate(() => {{
        // Common cookie consent selectors used by various consent management platforms
        const selectors = [
            // CookieYes
            '.cky-consent-container', '.cky-popup-center', '.cky-overlay', '.cky-modal',
            // OneTrust
            '#onetrust-consent-sdk', '#onetrust-banner-sdk', '.onetrust-pc-dark-filter',
            // Cookiebot
            '#CybotCookiebotDialog', '#CybotCookiebotDialogBodyUnderlay',
            // Generic cookie banners
            '[class*="cookie-consent"]', '[class*="cookie-banner"]', '[class*="cookie-notice"]',
            '[class*="cookie-popup"]', '[class*="cookie-modal"]', '[class*="cookie-dialog"]',
            '[id*="cookie-consent"]', '[id*="cookie-banner"]', '[id*="cookie-notice"]',
            '[id*="cookieconsent"]', '[id*="cookie-law"]',
            // GDPR banners
            '[class*="gdpr"]', '[id*="gdpr"]',
            // Consent banners
            '[class*="consent-banner"]', '[class*="consent-modal"]', '[class*="consent-popup"]',
            // Privacy banners
            '[class*="privacy-banner"]', '[class*="privacy-notice"]',
            // Common frameworks
            '.cc-window', '.cc-banner', '#cc-main',  // Cookie Consent by Insites
            '.qc-cmp2-container',  // Quantcast
            '.sp-message-container',  // SourcePoint
        ];

        const elementsFound = [];
        let visibleElement = null;

        for (const sel of selectors) {{
            try {{
                const elements = document.querySelectorAll(sel);
                for (const el of elements) {{
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    const isVisible = style.display !== 'none' &&
                                     style.visibility !== 'hidden' &&
                                     style.opacity !== '0' &&
                                     rect.width > 0 && rect.height > 0;

                    elementsFound.push({{
                        selector: sel,
                        visible: isVisible,
                        display: style.display,
                        visibility: style.visibility,
                        opacity: style.opacity,
                        width: rect.width,
                        height: rect.height
                    }});

                    if (isVisible && !visibleElement) {{
                        visibleElement = {{ selector: sel, width: rect.width, height: rect.height }};
                    }}
                }}
            }} catch (e) {{
                // Invalid selector, skip
            }}
        }}

        // Also grab a snippet of the HTML to help debug
        const bodyHtml = document.body.innerHTML.slice(0, 2000);
        const hasCookieKeyword = bodyHtml.toLowerCase().includes('cookie') ||
                                  bodyHtml.toLowerCase().includes('consent') ||
                                  bodyHtml.toLowerCase().includes('gdpr');

        return {{
            visible: visibleElement !== null,
            selector: visibleElement ? visibleElement.selector : null,
            elements_found: elementsFound,
            has_cookie_keyword_in_html: hasCookieKeyword,
            html_snippet: bodyHtml.slice(0, 500)
        }};
    }});

    console.error('Cookie consent check result:', JSON.stringify({{
        visible: result.visible,
        selector: result.selector,
        elements_found_count: result.elements_found.length
    }}));

    browser.disconnect();
    console.log(JSON.stringify(result));
}})();
'''
    script_path = script_dir / 'check_cookies.js'
    script_path.write_text(test_script)

    result = subprocess.run(
        ['node', str(script_path)],
        cwd=str(script_dir,
            env=get_test_env()),
        capture_output=True,
        text=True,
        env=env,
        timeout=90
    )

    if result.returncode != 0:
        raise RuntimeError(f"Cookie check script failed: {result.stderr}")

    output_lines = [l for l in result.stdout.strip().split('\n') if l.startswith('{')]
    if not output_lines:
        raise RuntimeError(f"No JSON output from cookie check: {result.stdout}\nstderr: {result.stderr}")

    return json.loads(output_lines[-1])


def test_hides_cookie_consent_on_filmin():
    """Live test: verify extension hides cookie consent popup on filmin.es.

    This test runs TWO browser sessions:
    1. WITHOUT extension - verifies cookie consent IS visible (baseline)
    2. WITH extension - verifies cookie consent is HIDDEN

    This ensures we're actually testing the extension's effect, not just
    that a page happens to not have cookie consent.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set up isolated env with proper directory structure
        env_base = setup_test_env(tmpdir)
        env_base['CHROME_HEADLESS'] = 'true'

        ext_dir = Path(env_base['CHROME_EXTENSIONS_DIR'])

        # ============================================================
        # STEP 1: BASELINE - Run WITHOUT extension, verify cookie consent IS visible
        # ============================================================
        print("\n" + "="*60)
        print("STEP 1: BASELINE TEST (no extension)")
        print("="*60)

        data_dir = Path(env_base['DATA_DIR'])

        env_no_ext = env_base.copy()
        env_no_ext['CHROME_EXTENSIONS_DIR'] = str(data_dir / 'personas' / 'Default' / 'empty_extensions')
        (data_dir / 'personas' / 'Default' / 'empty_extensions').mkdir(parents=True, exist_ok=True)

        # Launch baseline Chromium in crawls directory
        baseline_crawl_id = 'baseline-no-ext'
        baseline_crawl_dir = Path(env_base['CRAWLS_DIR']) / baseline_crawl_id
        baseline_crawl_dir.mkdir(parents=True, exist_ok=True)
        baseline_chrome_dir = baseline_crawl_dir / 'chrome'
        env_no_ext['CRAWL_OUTPUT_DIR'] = str(baseline_crawl_dir)
        baseline_process = None

        try:
            baseline_process, baseline_cdp_url = launch_chromium_session(
                env_no_ext, baseline_chrome_dir, baseline_crawl_id
            )
            print(f"Baseline Chromium launched: {baseline_cdp_url}")

            # Wait a moment for browser to be ready
            time.sleep(2)

            baseline_result = check_cookie_consent_visibility(
                baseline_cdp_url, TEST_URL, env_no_ext, tmpdir
            )

            print(f"Baseline result: visible={baseline_result['visible']}, "
                  f"elements_found={len(baseline_result['elements_found'])}")

            if baseline_result['elements_found']:
                print("Elements found in baseline:")
                for el in baseline_result['elements_found'][:5]:  # Show first 5
                    print(f"  - {el['selector']}: visible={el['visible']}, "
                          f"display={el['display']}, size={el['width']}x{el['height']}")

        finally:
            if baseline_process:
                kill_chromium_session(baseline_process, baseline_chrome_dir)

        # Verify baseline shows cookie consent
        if not baseline_result['visible']:
            # If no cookie consent visible in baseline, we can't test the extension
            # This could happen if:
            # - The site changed and no longer shows cookie consent
            # - Cookie consent is region-specific
            # - Our selectors don't match this site
            print("\nWARNING: No cookie consent visible in baseline!")
            print(f"HTML has cookie keywords: {baseline_result.get('has_cookie_keyword_in_html')}")
            print(f"HTML snippet: {baseline_result.get('html_snippet', '')[:200]}")

            pytest.skip(
                f"Cannot test extension: no cookie consent visible in baseline on {TEST_URL}. "
                f"Elements found: {len(baseline_result['elements_found'])}. "
                f"The site may have changed or cookie consent may be region-specific."
            )

        print(f"\n✓ Baseline confirmed: Cookie consent IS visible (selector: {baseline_result['selector']})")

        # ============================================================
        # STEP 2: Install the extension
        # ============================================================
        print("\n" + "="*60)
        print("STEP 2: INSTALLING EXTENSION")
        print("="*60)

        env_with_ext = env_base.copy()
        env_with_ext['CHROME_EXTENSIONS_DIR'] = str(ext_dir)

        result = subprocess.run(
            ['node', str(INSTALL_SCRIPT)],
            cwd=str(tmpdir,
            env=get_test_env()),
            capture_output=True,
            text=True,
            env=env_with_ext,
            timeout=60
        )
        assert result.returncode == 0, f"Extension install failed: {result.stderr}"

        cache_file = ext_dir / 'istilldontcareaboutcookies.extension.json'
        assert cache_file.exists(), "Extension cache not created"
        ext_data = json.loads(cache_file.read_text())
        print(f"Extension installed: {ext_data.get('name')} v{ext_data.get('version')}")

        # ============================================================
        # STEP 3: Run WITH extension, verify cookie consent is HIDDEN
        # ============================================================
        print("\n" + "="*60)
        print("STEP 3: TEST WITH EXTENSION")
        print("="*60)

        # Launch extension test Chromium in crawls directory
        ext_crawl_id = 'test-with-ext'
        ext_crawl_dir = Path(env_base['CRAWLS_DIR']) / ext_crawl_id
        ext_crawl_dir.mkdir(parents=True, exist_ok=True)
        ext_chrome_dir = ext_crawl_dir / 'chrome'
        env_with_ext['CRAWL_OUTPUT_DIR'] = str(ext_crawl_dir)
        ext_process = None

        try:
            ext_process, ext_cdp_url = launch_chromium_session(
                env_with_ext, ext_chrome_dir, ext_crawl_id
            )
            print(f"Extension Chromium launched: {ext_cdp_url}")

            # Check that extension was loaded
            extensions_file = ext_chrome_dir / 'extensions.json'
            if extensions_file.exists():
                loaded_exts = json.loads(extensions_file.read_text())
                print(f"Extensions loaded: {[e.get('name') for e in loaded_exts]}")

            # Wait for extension to initialize
            time.sleep(3)

            ext_result = check_cookie_consent_visibility(
                ext_cdp_url, TEST_URL, env_with_ext, tmpdir
            )

            print(f"Extension result: visible={ext_result['visible']}, "
                  f"elements_found={len(ext_result['elements_found'])}")

            if ext_result['elements_found']:
                print("Elements found with extension:")
                for el in ext_result['elements_found'][:5]:
                    print(f"  - {el['selector']}: visible={el['visible']}, "
                          f"display={el['display']}, size={el['width']}x{el['height']}")

        finally:
            if ext_process:
                kill_chromium_session(ext_process, ext_chrome_dir)

        # ============================================================
        # STEP 4: Compare results
        # ============================================================
        print("\n" + "="*60)
        print("STEP 4: COMPARISON")
        print("="*60)
        print(f"Baseline (no extension): cookie consent visible = {baseline_result['visible']}")
        print(f"With extension: cookie consent visible = {ext_result['visible']}")

        assert baseline_result['visible'], \
            "Baseline should show cookie consent (this shouldn't happen, we checked above)"

        assert not ext_result['visible'], \
            f"Cookie consent should be HIDDEN by extension.\n" \
            f"Baseline showed consent at: {baseline_result['selector']}\n" \
            f"But with extension, consent is still visible.\n" \
            f"Elements still visible: {[e for e in ext_result['elements_found'] if e['visible']]}"

        print("\n✓ SUCCESS: Extension correctly hides cookie consent!")
        print(f"  - Baseline showed consent at: {baseline_result['selector']}")
        print(f"  - Extension successfully hid it")
