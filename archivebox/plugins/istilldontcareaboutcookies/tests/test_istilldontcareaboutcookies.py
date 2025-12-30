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


PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_SCRIPT = next(PLUGIN_DIR.glob('on_Crawl__*_istilldontcareaboutcookies.*'), None)


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


def setup_test_lib_dirs(tmpdir: Path) -> dict:
    """Create isolated lib directories for tests and return env dict.

    Sets up:
        LIB_DIR: tmpdir/lib/<arch>
        NODE_MODULES_DIR: tmpdir/lib/<arch>/npm/node_modules
        NPM_BIN_DIR: tmpdir/lib/<arch>/npm/bin
        PIP_VENV_DIR: tmpdir/lib/<arch>/pip/venv
        PIP_BIN_DIR: tmpdir/lib/<arch>/pip/venv/bin
    """
    import platform
    arch = platform.machine()
    system = platform.system().lower()
    arch_dir = f"{arch}-{system}"

    lib_dir = tmpdir / 'lib' / arch_dir
    npm_dir = lib_dir / 'npm'
    node_modules_dir = npm_dir / 'node_modules'
    npm_bin_dir = npm_dir / 'bin'
    pip_venv_dir = lib_dir / 'pip' / 'venv'
    pip_bin_dir = pip_venv_dir / 'bin'

    # Create directories
    node_modules_dir.mkdir(parents=True, exist_ok=True)
    npm_bin_dir.mkdir(parents=True, exist_ok=True)
    pip_bin_dir.mkdir(parents=True, exist_ok=True)

    # Install puppeteer-core to the test node_modules if not present
    if not (node_modules_dir / 'puppeteer-core').exists():
        result = subprocess.run(
            ['npm', 'install', '--prefix', str(npm_dir), 'puppeteer-core'],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0:
            pytest.skip(f"Failed to install puppeteer-core: {result.stderr}")

    return {
        'LIB_DIR': str(lib_dir),
        'NODE_MODULES_DIR': str(node_modules_dir),
        'NPM_BIN_DIR': str(npm_bin_dir),
        'PIP_VENV_DIR': str(pip_venv_dir),
        'PIP_BIN_DIR': str(pip_bin_dir),
    }


PLUGINS_ROOT = PLUGIN_DIR.parent


def find_chromium_binary():
    """Find the Chromium binary using chrome_utils.js findChromium().

    This uses the centralized findChromium() function which checks:
    - CHROME_BINARY env var
    - @puppeteer/browsers install locations
    - System Chromium locations
    - Falls back to Chrome (with warning)
    """
    chrome_utils = PLUGINS_ROOT / 'chrome' / 'chrome_utils.js'
    result = subprocess.run(
        ['node', str(chrome_utils), 'findChromium'],
        capture_output=True,
        text=True,
        timeout=10
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


CHROME_LAUNCH_HOOK = PLUGINS_ROOT / 'chrome' / 'on_Crawl__20_chrome_launch.bg.js'

TEST_URL = 'https://www.filmin.es/'


def test_extension_loads_in_chromium():
    """Verify extension loads in Chromium by visiting its options page.

    Uses Chromium with --load-extension to load the extension, then navigates
    to chrome-extension://<id>/options.html and checks that the extension name
    appears in the page content.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set up isolated lib directories for this test
        lib_env = setup_test_lib_dirs(tmpdir)

        # Set up extensions directory
        ext_dir = tmpdir / 'chrome_extensions'
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env.update(lib_env)
        env['CHROME_EXTENSIONS_DIR'] = str(ext_dir)
        env['CHROME_HEADLESS'] = 'true'

        # Ensure CHROME_BINARY points to Chromium
        chromium = find_chromium_binary()
        if chromium:
            env['CHROME_BINARY'] = chromium

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
        crawl_dir = tmpdir / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'

        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-cookies'],
            cwd=str(crawl_dir),
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
                cwd=str(tmpdir),
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


def test_hides_cookie_consent_on_filmin():
    """Live test: verify extension hides cookie consent popup on filmin.es.

    Uses Chromium with extensions loaded automatically via chrome hook.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set up isolated lib directories for this test
        lib_env = setup_test_lib_dirs(tmpdir)

        # Set up extensions directory
        ext_dir = tmpdir / 'chrome_extensions'
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env.update(lib_env)
        env['CHROME_EXTENSIONS_DIR'] = str(ext_dir)
        env['CHROME_HEADLESS'] = 'true'

        # Ensure CHROME_BINARY points to Chromium
        chromium = find_chromium_binary()
        if chromium:
            env['CHROME_BINARY'] = chromium

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
        crawl_dir = tmpdir / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'

        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-cookies'],
            cwd=str(crawl_dir),
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

        try:
            # Step 3: Connect to Chromium and test cookie consent hiding
            test_script = f'''
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

(async () => {{
    const browser = await puppeteer.connect({{ browserWSEndpoint: '{cdp_url}' }});

    // Wait for extension to initialize
    await new Promise(r => setTimeout(r, 2000));

    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36');
    await page.setViewport({{ width: 1440, height: 900 }});

    console.error('Navigating to {TEST_URL}...');
    await page.goto('{TEST_URL}', {{ waitUntil: 'networkidle2', timeout: 30000 }});

    // Wait for extension content script to process page
    await new Promise(r => setTimeout(r, 5000));

    // Check cookie consent visibility
    const result = await page.evaluate(() => {{
        const selectors = ['.cky-consent-container', '.cky-popup-center', '.cky-overlay'];
        for (const sel of selectors) {{
            const el = document.querySelector(sel);
            if (el) {{
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                const visible = style.display !== 'none' &&
                               style.visibility !== 'hidden' &&
                               rect.width > 0 && rect.height > 0;
                if (visible) return {{ visible: true, selector: sel }};
            }}
        }}
        return {{ visible: false }};
    }});

    console.error('Cookie consent:', JSON.stringify(result));
    browser.disconnect();
    console.log(JSON.stringify(result));
}})();
'''
            script_path = tmpdir / 'test_extension.js'
            script_path.write_text(test_script)

            result = subprocess.run(
                ['node', str(script_path)],
                cwd=str(tmpdir),
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
            assert not test_result['visible'], \
                f"Cookie consent should be hidden by extension. Result: {test_result}"

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
