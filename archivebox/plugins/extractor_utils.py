#!/usr/bin/env python3
"""
Shared utilities for extractor hooks.

This module provides common functionality for all extractors to ensure
consistent behavior, output format, error handling, and timing.

All extractors should:
1. Import and use these utilities
2. Output consistent metadata (CMD, VERSION, OUTPUT, timing)
3. Write all files to $PWD
4. Return proper exit codes (0=success, 1=failure)
5. Be runnable standalone without any archivebox imports
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Static file extensions that generally don't need browser-based extraction
STATIC_EXTENSIONS = (
    '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico',
    '.mp4', '.mp3', '.m4a', '.webm', '.mkv', '.avi', '.mov',
    '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.exe', '.dmg', '.apk', '.deb', '.rpm',
)


def is_static_file(url: str) -> bool:
    """Check if URL points to a static file that may not need browser extraction."""
    return url.lower().split('?')[0].split('#')[0].endswith(STATIC_EXTENSIONS)


def get_env(name: str, default: str = '') -> str:
    """Get environment variable with default."""
    return os.environ.get(name, default).strip()


def get_env_bool(name: str, default: bool = False) -> bool:
    """Get boolean environment variable."""
    val = get_env(name, '').lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default


def get_env_int(name: str, default: int = 0) -> int:
    """Get integer environment variable."""
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def find_binary(bin_name: str, env_var: str | None = None) -> str | None:
    """Find binary from environment variable or PATH."""
    if env_var:
        binary = get_env(env_var)
        if binary and os.path.isfile(binary):
            return binary
    return shutil.which(bin_name)


def get_version(binary: str, version_args: list[str] | None = None) -> str:
    """Get binary version string."""
    if not binary or not os.path.isfile(binary):
        return ''

    args = version_args or ['--version']
    try:
        result = subprocess.run(
            [binary] + args,
            capture_output=True,
            text=True,
            timeout=10
        )
        # Return first non-empty line, truncated
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line:
                return line[:64]
        return ''
    except Exception:
        return ''


class ExtractorResult:
    """
    Tracks extractor execution and produces consistent output.

    Usage:
        result = ExtractorResult(name='wget', url=url)
        result.cmd = ['wget', url]
        result.version = '1.21'

        # ... do extraction ...

        result.output_str = 'example.com/index.html'
        result.status = 'succeeded'
        result.finish()

        sys.exit(result.exit_code)
    """

    def __init__(self, name: str, url: str, snapshot_id: str = ''):
        self.name = name
        self.url = url
        self.snapshot_id = snapshot_id
        self.start_ts = datetime.now(timezone.utc)
        self.end_ts: datetime | None = None

        self.cmd: list[str] = []
        self.version: str = ''
        self.output_str: str = ''  # Human-readable output summary
        self.status: str = 'failed'  # 'succeeded', 'failed', 'skipped'

        self.stdout: str = ''
        self.stderr: str = ''
        self.returncode: int | None = None

        self.error: str = ''
        self.hints: list[str] = []

        # Dependency info for missing binary
        self.dependency_needed: str = ''
        self.bin_providers: str = ''

    @property
    def duration(self) -> float:
        """Duration in seconds."""
        if self.end_ts:
            return (self.end_ts - self.start_ts).total_seconds()
        return (datetime.now(timezone.utc) - self.start_ts).total_seconds()

    @property
    def exit_code(self) -> int:
        """Exit code based on status."""
        if self.status == 'succeeded':
            return 0
        if self.status == 'skipped':
            return 0  # Skipped is not a failure
        return 1

    def finish(self, status: str | None = None):
        """Mark extraction as finished and print results."""
        self.end_ts = datetime.now(timezone.utc)
        if status:
            self.status = status
        self._print_results()

    def _print_results(self):
        """Print consistent output for hooks.py to parse."""
        import sys

        # Print timing
        print(f"START_TS={self.start_ts.isoformat()}")
        print(f"END_TS={self.end_ts.isoformat() if self.end_ts else ''}")
        print(f"DURATION={self.duration:.2f}")

        # Print command info
        if self.cmd:
            print(f"CMD={' '.join(str(c) for c in self.cmd)}")
        if self.version:
            print(f"VERSION={self.version}")

        # Print output path
        if self.output_str:
            print(f"OUTPUT={self.output_str}")

        # Print status
        print(f"STATUS={self.status}")

        # Print dependency info if needed
        if self.dependency_needed:
            print(f"DEPENDENCY_NEEDED={self.dependency_needed}", file=sys.stderr)
        if self.bin_providers:
            print(f"BIN_PROVIDERS={self.bin_providers}", file=sys.stderr)

        # Print error info
        if self.error:
            print(f"ERROR={self.error}", file=sys.stderr)
        for hint in self.hints:
            print(f"HINT={hint}", file=sys.stderr)

        # Print clean JSONL result for hooks.py to parse
        result_json = {
            'type': 'ArchiveResult',
            'status': self.status,
            'output_str': self.output_str or self.error or '',
        }
        if self.cmd:
            result_json['cmd'] = self.cmd
        if self.version:
            result_json['cmd_version'] = self.version
        print(json.dumps(result_json))


def run_shell_command(
    cmd: list[str],
    cwd: str | Path | None = None,
    timeout: int = 60,
    result: ExtractorResult | None = None,
) -> subprocess.CompletedProcess:
    """
    Run a shell command with proper capturing and timing.

    Updates result object if provided with stdout, stderr, returncode.
    """
    cwd = cwd or Path.cwd()

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            timeout=timeout,
        )

        if result:
            result.stdout = proc.stdout.decode('utf-8', errors='replace')
            result.stderr = proc.stderr.decode('utf-8', errors='replace')
            result.returncode = proc.returncode

        return proc

    except subprocess.TimeoutExpired as e:
        if result:
            result.error = f"Command timed out after {timeout} seconds"
            result.stdout = e.stdout.decode('utf-8', errors='replace') if e.stdout else ''
            result.stderr = e.stderr.decode('utf-8', errors='replace') if e.stderr else ''
        raise

    except Exception as e:
        if result:
            result.error = f"{type(e).__name__}: {e}"
        raise


def chrome_args(
    headless: bool = True,
    sandbox: bool = False,
    resolution: str = '1440,900',
    user_agent: str = '',
    check_ssl: bool = True,
    user_data_dir: str = '',
    profile_name: str = 'Default',
    extra_args: list[str] | None = None,
) -> list[str]:
    """
    Build Chrome/Chromium command line arguments.

    Based on the old CHROME_CONFIG.chrome_args() implementation.
    """
    args = [
        # Disable unnecessary features
        '--disable-sync',
        '--no-pings',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-default-apps',
        '--disable-infobars',
        '--disable-blink-features=AutomationControlled',

        # Deterministic behavior
        '--js-flags=--random-seed=1157259159',
        '--deterministic-mode',
        '--deterministic-fetch',

        # Performance
        '--disable-background-networking',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        '--disable-ipc-flooding-protection',

        # Disable prompts/popups
        '--deny-permission-prompts',
        '--disable-notifications',
        '--disable-popup-blocking',
        '--noerrdialogs',

        # Security/privacy
        '--disable-client-side-phishing-detection',
        '--disable-domain-reliability',
        '--disable-component-update',
        '--safebrowsing-disable-auto-update',
        '--password-store=basic',
        '--use-mock-keychain',

        # GPU/rendering
        '--force-gpu-mem-available-mb=4096',
        '--font-render-hinting=none',
        '--force-color-profile=srgb',
        '--disable-partial-raster',
        '--disable-skia-runtime-opts',
        '--disable-2d-canvas-clip-aa',
        '--disable-lazy-loading',

        # Media
        '--use-fake-device-for-media-stream',
        '--disable-gesture-requirement-for-media-playback',
    ]

    if headless:
        args.append('--headless=new')

    if not sandbox:
        args.extend([
            '--no-sandbox',
            '--no-zygote',
            '--disable-dev-shm-usage',
            '--disable-software-rasterizer',
        ])

    if resolution:
        args.append(f'--window-size={resolution}')

    if not check_ssl:
        args.extend([
            '--disable-web-security',
            '--ignore-certificate-errors',
        ])

    if user_agent:
        args.append(f'--user-agent={user_agent}')

    if user_data_dir:
        args.append(f'--user-data-dir={user_data_dir}')
        args.append(f'--profile-directory={profile_name}')

    if extra_args:
        args.extend(extra_args)

    return args


def chrome_cleanup_lockfile(user_data_dir: str | Path):
    """Remove Chrome SingletonLock file that can prevent browser from starting."""
    if not user_data_dir:
        return
    lockfile = Path(user_data_dir) / 'SingletonLock'
    try:
        lockfile.unlink(missing_ok=True)
    except Exception:
        pass


# Common Chrome binary names to search for
CHROME_BINARY_NAMES = [
    'google-chrome',
    'google-chrome-stable',
    'chromium',
    'chromium-browser',
    'chrome',
]
CHROME_BINARY_NAMES_MACOS = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
]


def find_chrome() -> str | None:
    """Find Chrome/Chromium binary."""
    # Check environment first
    chrome = get_env('CHROME_BINARY')
    if chrome and os.path.isfile(chrome):
        return chrome

    # Search PATH
    for name in CHROME_BINARY_NAMES:
        binary = shutil.which(name)
        if binary:
            return binary

    # Check macOS locations
    for path in CHROME_BINARY_NAMES_MACOS:
        if os.path.isfile(path):
            return path

    return None
