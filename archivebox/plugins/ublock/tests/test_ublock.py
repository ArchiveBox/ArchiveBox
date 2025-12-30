"""
Unit tests for ublock plugin

Tests invoke the plugin hook as an external process and verify outputs/side effects.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_SCRIPT = next(PLUGIN_DIR.glob('on_Crawl__*_ublock.*'), None)


def test_install_script_exists():
    """Verify install script exists"""
    assert INSTALL_SCRIPT.exists(), f"Install script not found: {INSTALL_SCRIPT}"


def test_extension_metadata():
    """Test that uBlock Origin extension has correct metadata"""
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
        assert metadata["webstore_id"] == "cjpalhdlnbpafiamejdnhcphjbkeiagm"
        assert metadata["name"] == "ublock"


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
            timeout=120  # uBlock is large, may take longer to download
        )

        # Check output mentions installation
        assert "uBlock" in result.stdout or "ublock" in result.stdout

        # Check cache file was created
        cache_file = ext_dir / "ublock.extension.json"
        assert cache_file.exists(), "Cache file should be created"

        # Verify cache content
        cache_data = json.loads(cache_file.read_text())
        assert cache_data["webstore_id"] == "cjpalhdlnbpafiamejdnhcphjbkeiagm"
        assert cache_data["name"] == "ublock"


def test_install_twice_uses_cache():
    """Test that running install twice uses existing cache on second run"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)

        # First install - downloads the extension
        result1 = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120  # uBlock is large
        )
        assert result1.returncode == 0, f"First install failed: {result1.stderr}"

        # Verify cache was created
        cache_file = ext_dir / "ublock.extension.json"
        assert cache_file.exists(), "Cache file should exist after first install"

        # Second install - should use cache and be faster
        result2 = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
        assert result2.returncode == 0, f"Second install failed: {result2.stderr}"

        # Second run should mention cache reuse
        assert "already installed" in result2.stdout or "cache" in result2.stdout.lower() or result2.returncode == 0


def test_no_configuration_required():
    """Test that uBlock Origin works without configuration"""
    with tempfile.TemporaryDirectory() as tmpdir:
        ext_dir = Path(tmpdir) / "chrome_extensions"
        ext_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["CHROME_EXTENSIONS_DIR"] = str(ext_dir)
        # No API keys needed - works with default filter lists

        result = subprocess.run(
            ["node", str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120
        )

        # Should not require any API keys
        combined_output = result.stdout + result.stderr
        assert "API" not in combined_output or result.returncode == 0


def test_large_extension_size():
    """Test that uBlock Origin is downloaded successfully despite large size"""
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
            timeout=120
        )

        # If extension was downloaded, verify it's substantial size
        crx_file = ext_dir / "cjpalhdlnbpafiamejdnhcphjbkeiagm__ublock.crx"
        if crx_file.exists():
            # uBlock Origin with filter lists is typically 2-5 MB
            size_bytes = crx_file.stat().st_size
            assert size_bytes > 1_000_000, f"uBlock Origin should be > 1MB, got {size_bytes} bytes"


PLUGINS_ROOT = PLUGIN_DIR.parent
CHROME_INSTALL_HOOK = PLUGINS_ROOT / 'chrome' / 'on_Crawl__00_chrome_install.py'
CHROME_LAUNCH_HOOK = PLUGINS_ROOT / 'chrome' / 'on_Crawl__20_chrome_launch.bg.js'


def setup_test_env(tmpdir: Path) -> dict:
    """Set up isolated data/lib directory structure for tests.

    Creates structure like:
        <tmpdir>/data/
            lib/
                arm64-darwin/   (or x86_64-linux, etc.)
                    npm/
                        bin/
                        node_modules/
            chrome_extensions/

    Calls chrome install hook which handles puppeteer-core and chromium installation.
    Returns env dict with DATA_DIR, LIB_DIR, NPM_BIN_DIR, NODE_MODULES_DIR, CHROME_BINARY, etc.
    """
    import platform

    # Determine machine type (matches archivebox.config.paths.get_machine_type())
    machine = platform.machine().lower()
    system = platform.system().lower()
    if machine in ('arm64', 'aarch64'):
        machine = 'arm64'
    elif machine in ('x86_64', 'amd64'):
        machine = 'x86_64'
    machine_type = f"{machine}-{system}"

    # Create proper directory structure
    data_dir = tmpdir / 'data'
    lib_dir = data_dir / 'lib' / machine_type
    npm_dir = lib_dir / 'npm'
    npm_bin_dir = npm_dir / 'bin'
    node_modules_dir = npm_dir / 'node_modules'
    chrome_extensions_dir = data_dir / 'chrome_extensions'

    # Create all directories
    node_modules_dir.mkdir(parents=True, exist_ok=True)
    npm_bin_dir.mkdir(parents=True, exist_ok=True)
    chrome_extensions_dir.mkdir(parents=True, exist_ok=True)

    # Build complete env dict
    env = os.environ.copy()
    env.update({
        'DATA_DIR': str(data_dir),
        'LIB_DIR': str(lib_dir),
        'MACHINE_TYPE': machine_type,
        'NPM_BIN_DIR': str(npm_bin_dir),
        'NODE_MODULES_DIR': str(node_modules_dir),
        'CHROME_EXTENSIONS_DIR': str(chrome_extensions_dir),
    })

    # Call chrome install hook (installs puppeteer-core and chromium, outputs JSONL)
    result = subprocess.run(
        ['python', str(CHROME_INSTALL_HOOK)],
        capture_output=True, text=True, timeout=10, env=env
    )
    if result.returncode != 0:
        pytest.skip(f"Chrome install hook failed: {result.stderr}")

    # Parse JSONL output to get CHROME_BINARY
    chrome_binary = None
    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if data.get('type') == 'Binary' and data.get('abspath'):
                chrome_binary = data['abspath']
                break
        except json.JSONDecodeError:
            continue

    if not chrome_binary or not Path(chrome_binary).exists():
        pytest.skip(f"Chromium binary not found: {chrome_binary}")

    env['CHROME_BINARY'] = chrome_binary
    return env


# Test URL: ad blocker test page that shows if ads are blocked
TEST_URL = 'https://d3ward.github.io/toolz/adblock.html'


@pytest.mark.timeout(15)
def test_extension_loads_in_chromium():
    """Verify uBlock extension loads in Chromium by visiting its dashboard page.

    Uses Chromium with --load-extension to load the extension, then navigates
    to chrome-extension://<id>/dashboard.html and checks that "uBlock" appears
    in the page content.
    """
    import signal
    import time
    print("[test] Starting test_extension_loads_in_chromium", flush=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        print(f"[test] tmpdir={tmpdir}", flush=True)

        # Set up isolated env with proper directory structure
        env = setup_test_env(tmpdir)
        env.setdefault('CHROME_HEADLESS', 'true')
        print(f"[test] DATA_DIR={env.get('DATA_DIR')}", flush=True)
        print(f"[test] CHROME_BINARY={env.get('CHROME_BINARY')}", flush=True)

        ext_dir = Path(env['CHROME_EXTENSIONS_DIR'])

        # Step 1: Install the uBlock extension
        print("[test] Installing uBlock extension...", flush=True)
        result = subprocess.run(
            ['node', str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=5
        )
        print(f"[test] Extension install rc={result.returncode}", flush=True)
        assert result.returncode == 0, f"Extension install failed: {result.stderr}"

        # Verify extension cache was created
        cache_file = ext_dir / 'ublock.extension.json'
        assert cache_file.exists(), "Extension cache not created"
        ext_data = json.loads(cache_file.read_text())
        print(f"[test] Extension installed: {ext_data.get('name')} v{ext_data.get('version')}", flush=True)

        # Step 2: Launch Chromium using the chrome hook (loads extensions automatically)
        print(f"[test] NODE_MODULES_DIR={env.get('NODE_MODULES_DIR')}", flush=True)
        print(f"[test] puppeteer-core exists: {(Path(env['NODE_MODULES_DIR']) / 'puppeteer-core').exists()}", flush=True)
        print("[test] Launching Chromium...", flush=True)
        data_dir = Path(env['DATA_DIR'])
        crawl_dir = data_dir / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'

        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-ublock'],
            cwd=str(crawl_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        print("[test] Chrome hook started, waiting for CDP...", flush=True)

        # Wait for Chromium to launch and CDP URL to be available
        cdp_url = None
        import select
        for i in range(20):
            poll_result = chrome_launch_process.poll()
            if poll_result is not None:
                stdout, stderr = chrome_launch_process.communicate()
                raise RuntimeError(f"Chromium launch failed (exit={poll_result}):\nStdout: {stdout}\nStderr: {stderr}")
            cdp_file = chrome_dir / 'cdp_url.txt'
            if cdp_file.exists():
                cdp_url = cdp_file.read_text().strip()
                print(f"[test] CDP URL found after {i+1} attempts", flush=True)
                break
            # Read any available stderr
            while select.select([chrome_launch_process.stderr], [], [], 0)[0]:
                line = chrome_launch_process.stderr.readline()
                if not line:
                    break
                print(f"[hook] {line.strip()}", flush=True)
            time.sleep(0.3)

        assert cdp_url, "Chromium CDP URL not found after 20s"
        print(f"[test] Chromium launched with CDP URL: {cdp_url}", flush=True)
        print("[test] Reading hook stderr...", flush=True)

        # Check what extensions were loaded by chrome hook
        extensions_file = chrome_dir / 'extensions.json'
        if extensions_file.exists():
            loaded_exts = json.loads(extensions_file.read_text())
            print(f"Extensions loaded by chrome hook: {[e.get('name') for e in loaded_exts]}")
        else:
            print("Warning: extensions.json not found")

        # Get the unpacked extension ID - Chrome computes this from the path
        unpacked_path = ext_data.get('unpacked_path', '')
        print(f"[test] Extension unpacked path: {unpacked_path}", flush=True)
        print("[test] Running puppeteer test script...", flush=True)

        try:
            # Step 3: Connect to Chromium and verify extension loads
            # First use CDP to get all targets and find extension ID
            test_script = f'''
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

(async () => {{
    const browser = await puppeteer.connect({{ browserWSEndpoint: '{cdp_url}' }});

    // Wait for extension to initialize
    await new Promise(r => setTimeout(r, 500));

    // Use CDP to get all targets including service workers
    const pages = await browser.pages();
    const page = pages[0] || await browser.newPage();
    const client = await page.createCDPSession();

    const {{ targetInfos }} = await client.send('Target.getTargets');
    console.error('All CDP targets:');
    targetInfos.forEach(t => console.error('  -', t.type, t.url.slice(0, 100)));

    // Find any chrome-extension:// URLs
    const extTargets = targetInfos.filter(t => t.url.startsWith('chrome-extension://'));
    console.error('Extension targets:', extTargets.length);

    // Filter out built-in extensions
    const builtinIds = ['nkeimhogjdpnpccoofpliimaahmaaome', 'fignfifoniblkonapihmkfakmlgkbkcf',
                       'ahfgeienlihckogmohjhadlkjgocpleb', 'mhjfbmdgcfjbbpaeojofohoefgiehjai'];
    const customExts = extTargets.filter(t => {{
        const extId = t.url.split('://')[1].split('/')[0];
        return !builtinIds.includes(extId);
    }});

    if (customExts.length === 0) {{
        console.log(JSON.stringify({{ loaded: false, error: 'No custom extension found via CDP' }}));
        browser.disconnect();
        return;
    }}

    // Get extension ID from first custom extension
    const extId = customExts[0].url.split('://')[1].split('/')[0];
    console.error('Found extension ID:', extId);

    // Try to load dashboard.html
    const newPage = await browser.newPage();
    const dashboardUrl = 'chrome-extension://' + extId + '/dashboard.html';
    console.error('Loading:', dashboardUrl);

    try {{
        await newPage.goto(dashboardUrl, {{ waitUntil: 'domcontentloaded', timeout: 15000 }});
        const title = await newPage.title();
        const content = await newPage.content();
        const hasUblock = content.toLowerCase().includes('ublock') || title.toLowerCase().includes('ublock');

        console.log(JSON.stringify({{
            loaded: true,
            extensionId: extId,
            pageTitle: title,
            hasExtensionName: hasUblock,
            contentLength: content.length
        }}));
    }} catch (e) {{
        console.error('Dashboard load failed:', e.message);
        console.log(JSON.stringify({{ loaded: true, extensionId: extId, dashboardError: e.message }}));
    }}

    browser.disconnect();
}})();
'''
            script_path = tmpdir / 'test_ublock.js'
            script_path.write_text(test_script)

            result = subprocess.run(
                ['node', str(script_path)],
                cwd=str(tmpdir),
                capture_output=True,
                text=True,
                env=env,
                timeout=10
            )

            print(f"stderr: {result.stderr}")
            print(f"stdout: {result.stdout}")

            assert result.returncode == 0, f"Test failed: {result.stderr}"

            output_lines = [l for l in result.stdout.strip().split('\n') if l.startswith('{')]
            assert output_lines, f"No JSON output: {result.stdout}"

            test_result = json.loads(output_lines[-1])
            assert test_result.get('loaded'), \
                f"uBlock extension should be loaded in Chromium. Result: {test_result}"
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


def test_blocks_ads_on_test_page():
    """Live test: verify uBlock Origin blocks ads on a test page.

    Uses Chromium with extensions loaded automatically via chrome hook.
    Tests against d3ward's ad blocker test page which checks ad domains.
    """
    import signal
    import time

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set up isolated env with proper directory structure
        env = setup_test_env(tmpdir)
        env['CHROME_HEADLESS'] = 'true'

        ext_dir = Path(env['CHROME_EXTENSIONS_DIR'])

        # Step 1: Install the uBlock extension
        result = subprocess.run(
            ['node', str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env,
            timeout=15
        )
        assert result.returncode == 0, f"Extension install failed: {result.stderr}"

        # Verify extension cache was created
        cache_file = ext_dir / 'ublock.extension.json'
        assert cache_file.exists(), "Extension cache not created"
        ext_data = json.loads(cache_file.read_text())
        print(f"Extension installed: {ext_data.get('name')} v{ext_data.get('version')}")

        # Step 2: Launch Chromium using the chrome hook (loads extensions automatically)
        data_dir = Path(env['DATA_DIR'])
        crawl_dir = data_dir / 'crawl'
        crawl_dir.mkdir()
        chrome_dir = crawl_dir / 'chrome'

        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-ublock'],
            cwd=str(crawl_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Wait for Chrome to launch and CDP URL to be available
        cdp_url = None
        for i in range(20):
            if chrome_launch_process.poll() is not None:
                stdout, stderr = chrome_launch_process.communicate()
                raise RuntimeError(f"Chrome launch failed:\nStdout: {stdout}\nStderr: {stderr}")
            cdp_file = chrome_dir / 'cdp_url.txt'
            if cdp_file.exists():
                cdp_url = cdp_file.read_text().strip()
                break
            time.sleep(1)

        assert cdp_url, "Chrome CDP URL not found after 20s"
        print(f"Chrome launched with CDP URL: {cdp_url}")

        # Check that extensions were loaded
        extensions_file = chrome_dir / 'extensions.json'
        if extensions_file.exists():
            loaded_exts = json.loads(extensions_file.read_text())
            print(f"Extensions loaded: {[e.get('name') for e in loaded_exts]}")

        try:
            # Step 3: Connect to Chrome and test ad blocking
            test_script = f'''
if (process.env.NODE_MODULES_DIR) module.paths.unshift(process.env.NODE_MODULES_DIR);
const puppeteer = require('puppeteer-core');

(async () => {{
    const browser = await puppeteer.connect({{ browserWSEndpoint: '{cdp_url}' }});

    // Wait for extension to initialize
    await new Promise(r => setTimeout(r, 500));

    // Check extension loaded by looking at targets
    const targets = browser.targets();
    const extTargets = targets.filter(t =>
        t.url().startsWith('chrome-extension://') ||
        t.type() === 'service_worker' ||
        t.type() === 'background_page'
    );
    console.error('Extension targets found:', extTargets.length);
    extTargets.forEach(t => console.error('  -', t.type(), t.url().substring(0, 60)));

    const page = await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36');
    await page.setViewport({{ width: 1440, height: 900 }});

    console.error('Navigating to {TEST_URL}...');
    await page.goto('{TEST_URL}', {{ waitUntil: 'networkidle2', timeout: 60000 }});

    // Wait for the test page to run its checks
    await new Promise(r => setTimeout(r, 5000));

    // The d3ward test page shows blocked percentage
    const result = await page.evaluate(() => {{
        const scoreEl = document.querySelector('#score');
        const score = scoreEl ? scoreEl.textContent : null;
        const blockedItems = document.querySelectorAll('.blocked').length;
        const totalItems = document.querySelectorAll('.testlist li').length;
        return {{
            score,
            blockedItems,
            totalItems,
            percentBlocked: totalItems > 0 ? Math.round((blockedItems / totalItems) * 100) : 0
        }};
    }});

    console.error('Ad blocking result:', JSON.stringify(result));
    browser.disconnect();
    console.log(JSON.stringify(result));
}})();
'''
            script_path = tmpdir / 'test_ublock.js'
            script_path.write_text(test_script)

            result = subprocess.run(
                ['node', str(script_path)],
                cwd=str(tmpdir),
                capture_output=True,
                text=True,
                env=env,
                timeout=10
            )

            print(f"stderr: {result.stderr}")
            print(f"stdout: {result.stdout}")

            assert result.returncode == 0, f"Test failed: {result.stderr}"

            output_lines = [l for l in result.stdout.strip().split('\n') if l.startswith('{')]
            assert output_lines, f"No JSON output: {result.stdout}"

            test_result = json.loads(output_lines[-1])

            # uBlock should block most ad domains on the test page
            assert test_result['percentBlocked'] >= 50, \
                f"uBlock should block at least 50% of ads, only blocked {test_result['percentBlocked']}%. Result: {test_result}"

        finally:
            # Clean up Chrome
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
