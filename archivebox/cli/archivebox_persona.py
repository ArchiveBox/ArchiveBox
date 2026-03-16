#!/usr/bin/env python3

"""
archivebox persona <action> [args...] [--filters]

Manage Persona records (browser profiles for archiving).

Actions:
    create  - Create Personas
    list    - List Personas as JSONL (with optional filters)
    update  - Update Personas from stdin JSONL
    delete  - Delete Personas from stdin JSONL

Examples:
    # Create a new persona
    archivebox persona create work
    archivebox persona create --import=chrome personal
    archivebox persona create --import=edge work

    # List all personas
    archivebox persona list

    # Delete a persona
    archivebox persona list --name=old | archivebox persona delete --yes
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox persona'

import os
import sys
import shutil
import platform
import subprocess
import tempfile
import json
from pathlib import Path
from typing import Optional, Iterable
from collections import OrderedDict

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_utils import apply_filters


# =============================================================================
# Browser Profile Locations
# =============================================================================

def get_chrome_user_data_dir() -> Optional[Path]:
    """Get the default Chrome user data directory for the current platform."""
    system = platform.system()
    home = Path.home()

    if system == 'Darwin':  # macOS
        candidates = [
            home / 'Library' / 'Application Support' / 'Google' / 'Chrome',
            home / 'Library' / 'Application Support' / 'Chromium',
        ]
    elif system == 'Linux':
        candidates = [
            home / '.config' / 'google-chrome',
            home / '.config' / 'chromium',
            home / '.config' / 'chrome',
            home / 'snap' / 'chromium' / 'common' / 'chromium',
        ]
    elif system == 'Windows':
        local_app_data = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
        candidates = [
            local_app_data / 'Google' / 'Chrome' / 'User Data',
            local_app_data / 'Chromium' / 'User Data',
        ]
    else:
        candidates = []

    for candidate in candidates:
        if candidate.exists() and (candidate / 'Default').exists():
            return candidate

    return None


def get_brave_user_data_dir() -> Optional[Path]:
    """Get the default Brave user data directory for the current platform."""
    system = platform.system()
    home = Path.home()

    if system == 'Darwin':
        candidates = [
            home / 'Library' / 'Application Support' / 'BraveSoftware' / 'Brave-Browser',
        ]
    elif system == 'Linux':
        candidates = [
            home / '.config' / 'BraveSoftware' / 'Brave-Browser',
        ]
    elif system == 'Windows':
        local_app_data = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
        candidates = [
            local_app_data / 'BraveSoftware' / 'Brave-Browser' / 'User Data',
        ]
    else:
        candidates = []

    for candidate in candidates:
        if candidate.exists() and (candidate / 'Default').exists():
            return candidate

    return None


def get_edge_user_data_dir() -> Optional[Path]:
    """Get the default Edge user data directory for the current platform."""
    system = platform.system()
    home = Path.home()

    if system == 'Darwin':
        candidates = [
            home / 'Library' / 'Application Support' / 'Microsoft Edge',
        ]
    elif system == 'Linux':
        candidates = [
            home / '.config' / 'microsoft-edge',
            home / '.config' / 'microsoft-edge-beta',
            home / '.config' / 'microsoft-edge-dev',
        ]
    elif system == 'Windows':
        local_app_data = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
        candidates = [
            local_app_data / 'Microsoft' / 'Edge' / 'User Data',
        ]
    else:
        candidates = []

    for candidate in candidates:
        if candidate.exists() and (candidate / 'Default').exists():
            return candidate

    return None


def get_browser_binary(browser: str) -> Optional[str]:
    system = platform.system()
    home = Path.home()
    browser = browser.lower()

    if system == 'Darwin':
        candidates = {
            'chrome': ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'],
            'chromium': ['/Applications/Chromium.app/Contents/MacOS/Chromium'],
            'brave': ['/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'],
            'edge': ['/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'],
        }.get(browser, [])
    elif system == 'Linux':
        candidates = {
            'chrome': ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/google-chrome-beta', '/usr/bin/google-chrome-unstable'],
            'chromium': ['/usr/bin/chromium', '/usr/bin/chromium-browser'],
            'brave': ['/usr/bin/brave-browser', '/usr/bin/brave-browser-beta', '/usr/bin/brave-browser-nightly'],
            'edge': ['/usr/bin/microsoft-edge', '/usr/bin/microsoft-edge-stable', '/usr/bin/microsoft-edge-beta', '/usr/bin/microsoft-edge-dev'],
        }.get(browser, [])
    elif system == 'Windows':
        local_app_data = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
        candidates = {
            'chrome': [
                str(local_app_data / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'),
                'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
                'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
            ],
            'chromium': [str(local_app_data / 'Chromium' / 'Application' / 'chrome.exe')],
            'brave': [
                str(local_app_data / 'BraveSoftware' / 'Brave-Browser' / 'Application' / 'brave.exe'),
                'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe',
                'C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe',
            ],
            'edge': [
                str(local_app_data / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe'),
                'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
                'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
            ],
        }.get(browser, [])
    else:
        candidates = []

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate

    return None


BROWSER_PROFILE_FINDERS = {
    'chrome': get_chrome_user_data_dir,
    'chromium': get_chrome_user_data_dir,  # Same locations
    'brave': get_brave_user_data_dir,
    'edge': get_edge_user_data_dir,
}

CHROMIUM_BROWSERS = {'chrome', 'chromium', 'brave', 'edge'}


# =============================================================================
# Cookie Extraction via CDP
# =============================================================================

NETSCAPE_COOKIE_HEADER = [
    '# Netscape HTTP Cookie File',
    '# https://curl.se/docs/http-cookies.html',
    '# This file was generated by ArchiveBox persona cookie extraction',
    '#',
    '# Format: domain\\tincludeSubdomains\\tpath\\tsecure\\texpiry\\tname\\tvalue',
    '',
]


def _parse_netscape_cookies(path: Path) -> "OrderedDict[tuple[str, str, str], tuple[str, str, str, str, str, str, str]]":
    cookies = OrderedDict()
    if not path.exists():
        return cookies

    for line in path.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) < 7:
            continue
        domain, include_subdomains, cookie_path, secure, expiry, name, value = parts[:7]
        key = (domain, cookie_path, name)
        cookies[key] = (domain, include_subdomains, cookie_path, secure, expiry, name, value)
    return cookies


def _write_netscape_cookies(path: Path, cookies: "OrderedDict[tuple[str, str, str], tuple[str, str, str, str, str, str, str]]") -> None:
    lines = list(NETSCAPE_COOKIE_HEADER)
    for cookie in cookies.values():
        lines.append('\t'.join(cookie))
    path.write_text('\n'.join(lines) + '\n')


def _merge_netscape_cookies(existing_file: Path, new_file: Path) -> None:
    existing = _parse_netscape_cookies(existing_file)
    new = _parse_netscape_cookies(new_file)
    for key, cookie in new.items():
        existing[key] = cookie
    _write_netscape_cookies(existing_file, existing)


def extract_cookies_via_cdp(
    user_data_dir: Path,
    output_file: Path,
    profile_dir: str | None = None,
    chrome_binary: str | None = None,
) -> bool:
    """
    Launch Chrome with the given user data dir and extract cookies via CDP.

    Returns True if successful, False otherwise.
    """
    from archivebox.config.common import STORAGE_CONFIG

    # Find the cookie extraction script
    chrome_plugin_dir = Path(__file__).parent.parent / 'plugins' / 'chrome'
    extract_script = chrome_plugin_dir / 'extract_cookies.js'

    if not extract_script.exists():
        rprint(f'[yellow]Cookie extraction script not found at {extract_script}[/yellow]', file=sys.stderr)
        return False

    # Get node modules dir
    node_modules_dir = STORAGE_CONFIG.LIB_DIR / 'npm' / 'node_modules'

    # Set up environment
    env = os.environ.copy()
    env['NODE_MODULES_DIR'] = str(node_modules_dir)
    env['CHROME_USER_DATA_DIR'] = str(user_data_dir)
    env['CHROME_HEADLESS'] = 'true'
    if chrome_binary:
        env['CHROME_BINARY'] = str(chrome_binary)
    output_path = output_file
    temp_output = None
    temp_dir = None
    if output_file.exists():
        temp_dir = Path(tempfile.mkdtemp(prefix='ab_cookies_'))
        temp_output = temp_dir / 'cookies.txt'
        output_path = temp_output
    if profile_dir:
        extra_arg = f'--profile-directory={profile_dir}'
        existing_extra = env.get('CHROME_ARGS_EXTRA', '').strip()
        args_list = []
        if existing_extra:
            if existing_extra.startswith('['):
                try:
                    parsed = json.loads(existing_extra)
                    if isinstance(parsed, list):
                        args_list.extend(str(x) for x in parsed)
                except Exception:
                    args_list.extend([s.strip() for s in existing_extra.split(',') if s.strip()])
            else:
                args_list.extend([s.strip() for s in existing_extra.split(',') if s.strip()])
        args_list.append(extra_arg)
        env['CHROME_ARGS_EXTRA'] = json.dumps(args_list)

    env['COOKIES_OUTPUT_FILE'] = str(output_path)

    try:
        result = subprocess.run(
            ['node', str(extract_script)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            if temp_output and temp_output.exists():
                _merge_netscape_cookies(output_file, temp_output)
            return True
        else:
            rprint(f'[yellow]Cookie extraction failed: {result.stderr}[/yellow]', file=sys.stderr)
            return False

    except subprocess.TimeoutExpired:
        rprint('[yellow]Cookie extraction timed out[/yellow]', file=sys.stderr)
        return False
    except FileNotFoundError:
        rprint('[yellow]Node.js not found. Cannot extract cookies.[/yellow]', file=sys.stderr)
        return False
    except Exception as e:
        rprint(f'[yellow]Cookie extraction error: {e}[/yellow]', file=sys.stderr)
        return False
    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# Validation Helpers
# =============================================================================

def validate_persona_name(name: str) -> tuple[bool, str]:
    """
    Validate persona name to prevent path traversal attacks.

    Returns:
        (is_valid, error_message): tuple indicating if name is valid
    """
    if not name or not name.strip():
        return False, "Persona name cannot be empty"

    # Check for path separators
    if '/' in name or '\\' in name:
        return False, "Persona name cannot contain path separators (/ or \\)"

    # Check for parent directory references
    if '..' in name:
        return False, "Persona name cannot contain parent directory references (..)"

    # Check for hidden files/directories
    if name.startswith('.'):
        return False, "Persona name cannot start with a dot (.)"

    # Ensure name doesn't contain null bytes or other dangerous chars
    if '\x00' in name or '\n' in name or '\r' in name:
        return False, "Persona name contains invalid characters"

    return True, ""


def ensure_path_within_personas_dir(persona_path: Path) -> bool:
    """
    Verify that a persona path is within PERSONAS_DIR.

    This is a safety check to prevent path traversal attacks where
    a malicious persona name could cause operations on paths outside
    the expected PERSONAS_DIR.

    Returns:
        True if path is safe, False otherwise
    """
    from archivebox.config.constants import CONSTANTS

    try:
        # Resolve both paths to absolute paths
        personas_dir = CONSTANTS.PERSONAS_DIR.resolve()
        resolved_path = persona_path.resolve()

        # Check if resolved_path is a child of personas_dir
        return resolved_path.is_relative_to(personas_dir)
    except (ValueError, RuntimeError):
        return False


# =============================================================================
# CREATE
# =============================================================================

def create_personas(
    names: Iterable[str],
    import_from: Optional[str] = None,
    profile: Optional[str] = None,
) -> int:
    """
    Create Personas from names.

    If --import is specified, copy the browser profile to the persona directory
    and extract cookies.

    Exit codes:
        0: Success
        1: Failure
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.personas.models import Persona
    from archivebox.config.constants import CONSTANTS

    is_tty = sys.stdout.isatty()
    name_list = list(names) if names else []

    if not name_list:
        rprint('[yellow]No persona names provided. Pass names as arguments.[/yellow]', file=sys.stderr)
        return 1

    # Validate import source if specified
    source_profile_dir = None
    if import_from:
        import_from = import_from.lower()
        if import_from not in BROWSER_PROFILE_FINDERS:
            rprint(f'[red]Unknown browser: {import_from}[/red]', file=sys.stderr)
            rprint(f'[dim]Supported browsers: {", ".join(BROWSER_PROFILE_FINDERS.keys())}[/dim]', file=sys.stderr)
            return 1

        source_profile_dir = BROWSER_PROFILE_FINDERS[import_from]()
        if not source_profile_dir:
            rprint(f'[red]Could not find {import_from} profile directory[/red]', file=sys.stderr)
            return 1

        rprint(f'[dim]Found {import_from} profile: {source_profile_dir}[/dim]', file=sys.stderr)

        if profile is None and (source_profile_dir / 'Default').exists():
            profile = 'Default'

        browser_binary = get_browser_binary(import_from)
        if browser_binary:
            rprint(f'[dim]Using {import_from} binary: {browser_binary}[/dim]', file=sys.stderr)
    else:
        browser_binary = None

    created_count = 0
    for name in name_list:
        name = name.strip()
        if not name:
            continue

        # Validate persona name to prevent path traversal
        is_valid, error_msg = validate_persona_name(name)
        if not is_valid:
            rprint(f'[red]Invalid persona name "{name}": {error_msg}[/red]', file=sys.stderr)
            continue

        persona, created = Persona.objects.get_or_create(name=name)

        if created:
            persona.ensure_dirs()
            created_count += 1
            rprint(f'[green]Created persona: {name}[/green]', file=sys.stderr)
        else:
            rprint(f'[dim]Persona already exists: {name}[/dim]', file=sys.stderr)

        # Import browser profile if requested
        if import_from and source_profile_dir:
            cookies_file = Path(persona.path) / 'cookies.txt'

        if import_from in CHROMIUM_BROWSERS:
            persona_chrome_dir = Path(persona.CHROME_USER_DATA_DIR)

            # Copy the browser profile
            rprint(f'[dim]Copying browser profile to {persona_chrome_dir}...[/dim]', file=sys.stderr)

            try:
                # Remove existing chrome_user_data if it exists
                if persona_chrome_dir.exists():
                    shutil.rmtree(persona_chrome_dir)

                # Copy the profile directory
                # We copy the entire user data dir, not just Default profile
                shutil.copytree(
                    source_profile_dir,
                    persona_chrome_dir,
                    symlinks=True,
                    ignore=shutil.ignore_patterns(
                        'Cache', 'Code Cache', 'GPUCache', 'ShaderCache',
                        'Service Worker', 'GCM Store', '*.log', 'Crashpad',
                        'BrowserMetrics', 'BrowserMetrics-spare.pma',
                        'SingletonLock', 'SingletonSocket', 'SingletonCookie',
                    ),
                )
                rprint(f'[green]Copied browser profile to persona[/green]', file=sys.stderr)

                # Extract cookies via CDP
                rprint(f'[dim]Extracting cookies via CDP...[/dim]', file=sys.stderr)

                if extract_cookies_via_cdp(
                    persona_chrome_dir,
                    cookies_file,
                    profile_dir=profile,
                    chrome_binary=browser_binary,
                ):
                    rprint(f'[green]Extracted cookies to {cookies_file}[/green]', file=sys.stderr)
                else:
                    rprint(f'[yellow]Could not extract cookies automatically.[/yellow]', file=sys.stderr)
                    rprint(f'[dim]You can manually export cookies using a browser extension.[/dim]', file=sys.stderr)

            except Exception as e:
                rprint(f'[red]Failed to copy browser profile: {e}[/red]', file=sys.stderr)
                return 1

        if not is_tty:
            write_record({
                'id': str(persona.id) if hasattr(persona, 'id') else None,
                'name': persona.name,
                'path': str(persona.path),
                'CHROME_USER_DATA_DIR': persona.CHROME_USER_DATA_DIR,
                'COOKIES_FILE': persona.COOKIES_FILE,
            })

    rprint(f'[green]Created {created_count} new persona(s)[/green]', file=sys.stderr)
    return 0


# =============================================================================
# LIST
# =============================================================================

def list_personas(
    name: Optional[str] = None,
    name__icontains: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    List Personas as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.personas.models import Persona

    is_tty = sys.stdout.isatty()

    queryset = Persona.objects.all().order_by('name')

    # Apply filters
    filter_kwargs = {
        'name': name,
        'name__icontains': name__icontains,
    }
    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    count = 0
    for persona in queryset:
        cookies_status = '[green]✓[/green]' if persona.COOKIES_FILE else '[dim]✗[/dim]'
        chrome_status = '[green]✓[/green]' if Path(persona.CHROME_USER_DATA_DIR).exists() else '[dim]✗[/dim]'

        if is_tty:
            rprint(f'[cyan]{persona.name:20}[/cyan] cookies:{cookies_status} chrome:{chrome_status} [dim]{persona.path}[/dim]')
        else:
            write_record({
                'id': str(persona.id) if hasattr(persona, 'id') else None,
                'name': persona.name,
                'path': str(persona.path),
                'CHROME_USER_DATA_DIR': persona.CHROME_USER_DATA_DIR,
                'COOKIES_FILE': persona.COOKIES_FILE,
            })
        count += 1

    rprint(f'[dim]Listed {count} persona(s)[/dim]', file=sys.stderr)
    return 0


# =============================================================================
# UPDATE
# =============================================================================

def update_personas(name: Optional[str] = None) -> int:
    """
    Update Personas from stdin JSONL.

    Reads Persona records from stdin and applies updates.
    Uses PATCH semantics - only specified fields are updated.

    Exit codes:
        0: Success
        1: No input or error
    """
    from archivebox.misc.jsonl import read_stdin, write_record
    from archivebox.personas.models import Persona

    is_tty = sys.stdout.isatty()

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    updated_count = 0
    for record in records:
        persona_id = record.get('id')
        old_name = record.get('name')

        if not persona_id and not old_name:
            continue

        try:
            if persona_id:
                persona = Persona.objects.get(id=persona_id)
            else:
                persona = Persona.objects.get(name=old_name)

            # Apply updates from CLI flags
            if name:
                # Validate new name to prevent path traversal
                is_valid, error_msg = validate_persona_name(name)
                if not is_valid:
                    rprint(f'[red]Invalid new persona name "{name}": {error_msg}[/red]', file=sys.stderr)
                    continue

                # Rename the persona directory too
                old_path = persona.path
                persona.name = name
                new_path = persona.path

                if old_path.exists() and old_path != new_path:
                    shutil.move(str(old_path), str(new_path))

                persona.save()

            updated_count += 1

            if not is_tty:
                write_record({
                    'id': str(persona.id) if hasattr(persona, 'id') else None,
                    'name': persona.name,
                    'path': str(persona.path),
                })

        except Persona.DoesNotExist:
            rprint(f'[yellow]Persona not found: {persona_id or old_name}[/yellow]', file=sys.stderr)
            continue

    rprint(f'[green]Updated {updated_count} persona(s)[/green]', file=sys.stderr)
    return 0


# =============================================================================
# DELETE
# =============================================================================

def delete_personas(yes: bool = False, dry_run: bool = False) -> int:
    """
    Delete Personas from stdin JSONL.

    Requires --yes flag to confirm deletion.

    Exit codes:
        0: Success
        1: No input or missing --yes flag
    """
    from archivebox.misc.jsonl import read_stdin
    from archivebox.personas.models import Persona

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    # Collect persona IDs or names
    persona_ids = []
    persona_names = []
    for r in records:
        if r.get('id'):
            persona_ids.append(r['id'])
        elif r.get('name'):
            persona_names.append(r['name'])

    if not persona_ids and not persona_names:
        rprint('[yellow]No valid persona IDs or names in input[/yellow]', file=sys.stderr)
        return 1

    from django.db.models import Q
    query = Q()
    if persona_ids:
        query |= Q(id__in=persona_ids)
    if persona_names:
        query |= Q(name__in=persona_names)

    personas = Persona.objects.filter(query)
    count = personas.count()

    if count == 0:
        rprint('[yellow]No matching personas found[/yellow]', file=sys.stderr)
        return 0

    if dry_run:
        rprint(f'[yellow]Would delete {count} persona(s) (dry run)[/yellow]', file=sys.stderr)
        for persona in personas:
            rprint(f'  {persona.name} ({persona.path})', file=sys.stderr)
        return 0

    if not yes:
        rprint('[red]Use --yes to confirm deletion[/red]', file=sys.stderr)
        return 1

    # Delete persona directories and database records
    deleted_count = 0
    for persona in personas:
        persona_path = persona.path

        # Safety check: ensure path is within PERSONAS_DIR before deletion
        if not ensure_path_within_personas_dir(persona_path):
            rprint(f'[red]Security error: persona path "{persona_path}" is outside PERSONAS_DIR. Skipping deletion.[/red]', file=sys.stderr)
            continue

        if persona_path.exists():
            shutil.rmtree(persona_path)
        persona.delete()
        deleted_count += 1

    rprint(f'[green]Deleted {deleted_count} persona(s)[/green]', file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================

@click.group()
def main():
    """Manage Persona records (browser profiles)."""
    pass


@main.command('create')
@click.argument('names', nargs=-1)
@click.option('--import', 'import_from', help='Import profile from browser (chrome, chromium, brave, edge)')
@click.option('--profile', help='Profile directory name under the user data dir (e.g. Default, Profile 1)')
def create_cmd(names: tuple, import_from: Optional[str], profile: Optional[str]):
    """Create Personas, optionally importing from a browser profile."""
    sys.exit(create_personas(names, import_from=import_from, profile=profile))


@main.command('list')
@click.option('--name', help='Filter by exact name')
@click.option('--name__icontains', help='Filter by name contains')
@click.option('--limit', '-n', type=int, help='Limit number of results')
def list_cmd(name: Optional[str], name__icontains: Optional[str], limit: Optional[int]):
    """List Personas as JSONL."""
    sys.exit(list_personas(name=name, name__icontains=name__icontains, limit=limit))


@main.command('update')
@click.option('--name', '-n', help='Set new name')
def update_cmd(name: Optional[str]):
    """Update Personas from stdin JSONL."""
    sys.exit(update_personas(name=name))


@main.command('delete')
@click.option('--yes', '-y', is_flag=True, help='Confirm deletion')
@click.option('--dry-run', is_flag=True, help='Show what would be deleted')
def delete_cmd(yes: bool, dry_run: bool):
    """Delete Personas from stdin JSONL."""
    sys.exit(delete_personas(yes=yes, dry_run=dry_run))


if __name__ == '__main__':
    main()
