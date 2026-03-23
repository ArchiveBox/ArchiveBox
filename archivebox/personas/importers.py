"""
Shared persona browser discovery/import helpers.

These helpers are used by both the CLI and the Django admin so Persona import
behavior stays consistent regardless of where it is triggered from.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

from django.utils.html import format_html
from django.utils.safestring import SafeString

if TYPE_CHECKING:
    from archivebox.personas.models import Persona


BROWSER_LABELS = {
    "chrome": "Google Chrome",
    "chromium": "Chromium",
    "brave": "Brave",
    "edge": "Microsoft Edge",
    "custom": "Custom Path",
    "persona": "Persona Template",
}

BROWSER_PROFILE_DIR_NAMES = (
    "Default",
    "Profile ",
    "Guest Profile",
)

VOLATILE_PROFILE_COPY_PATTERNS = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "ShaderCache",
    "Service Worker",
    "GCM Store",
    "*.log",
    "Crashpad",
    "BrowserMetrics",
    "BrowserMetrics-spare.pma",
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
)

PERSONA_PROFILE_DIR_CANDIDATES = (
    "chrome_profile",
    "chrome_user_data",
)


@dataclass(frozen=True)
class PersonaImportSource:
    kind: str
    browser: str = "custom"
    source_name: str | None = None
    user_data_dir: Path | None = None
    profile_dir: str | None = None
    browser_binary: str | None = None
    cdp_url: str | None = None

    @property
    def browser_label(self) -> str:
        return BROWSER_LABELS.get(self.browser, self.browser.title())

    @property
    def profile_path(self) -> Path | None:
        if not self.user_data_dir or not self.profile_dir:
            return None
        return self.user_data_dir / self.profile_dir

    @property
    def display_label(self) -> str:
        if self.kind == "cdp":
            return self.cdp_url or "CDP URL"
        profile_suffix = f" / {self.profile_dir}" if self.profile_dir else ""
        source_prefix = f": {self.source_name}" if self.source_name else ""
        return f"{self.browser_label}{source_prefix}{profile_suffix}"

    @property
    def choice_value(self) -> str:
        return json.dumps(
            {
                "kind": self.kind,
                "browser": self.browser,
                "source_name": self.source_name or "",
                "user_data_dir": str(self.user_data_dir) if self.user_data_dir else "",
                "profile_dir": self.profile_dir or "",
                "browser_binary": self.browser_binary or "",
                "cdp_url": self.cdp_url or "",
            },
            sort_keys=True,
        )

    def as_choice_label(self) -> SafeString:
        path_str = str(self.profile_path or self.user_data_dir or self.cdp_url or "")
        binary_suffix = f"Using {self.browser_binary}" if self.browser_binary else "Will auto-detect a Chromium binary"
        return format_html(
            '<span class="abx-profile-option">'
            '<strong>{}</strong>'
            '<span class="abx-profile-option__meta">{}</span>'
            '<code>{}</code>'
            "</span>",
            self.display_label,
            binary_suffix,
            path_str,
        )

    @classmethod
    def from_choice_value(cls, value: str) -> "PersonaImportSource":
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as err:
            raise ValueError("Invalid discovered profile selection.") from err

        if payload.get("kind") != "browser-profile":
            raise ValueError("Invalid discovered profile selection.")

        user_data_dir = Path(str(payload.get("user_data_dir") or "")).expanduser()
        profile_dir = str(payload.get("profile_dir") or "").strip()
        browser = str(payload.get("browser") or "custom").strip().lower() or "custom"
        source_name = str(payload.get("source_name") or "").strip() or None
        browser_binary = str(payload.get("browser_binary") or "").strip() or None

        return resolve_browser_profile_source(
            browser=browser,
            source_name=source_name,
            user_data_dir=user_data_dir,
            profile_dir=profile_dir,
            browser_binary=browser_binary,
        )


@dataclass
class PersonaImportResult:
    source: PersonaImportSource
    profile_copied: bool = False
    cookies_imported: bool = False
    storage_captured: bool = False
    user_agent_imported: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def did_work(self) -> bool:
        return self.profile_copied or self.cookies_imported or self.storage_captured or self.user_agent_imported


def get_chrome_user_data_dir() -> Optional[Path]:
    """Get the default Chrome user data directory for the current platform."""
    system = platform.system()
    home = Path.home()

    if system == "Darwin":
        candidates = [
            home / "Library" / "Application Support" / "Google" / "Chrome",
            home / "Library" / "Application Support" / "Chromium",
        ]
    elif system == "Linux":
        candidates = [
            home / ".config" / "google-chrome",
            home / ".config" / "chromium",
            home / ".config" / "chrome",
            home / "snap" / "chromium" / "common" / "chromium",
        ]
    elif system == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates = [
            local_app_data / "Google" / "Chrome" / "User Data",
            local_app_data / "Chromium" / "User Data",
        ]
    else:
        candidates = []

    for candidate in candidates:
        if candidate.exists() and _list_profile_names(candidate):
            return candidate

    return None


def get_brave_user_data_dir() -> Optional[Path]:
    """Get the default Brave user data directory for the current platform."""
    system = platform.system()
    home = Path.home()

    if system == "Darwin":
        candidates = [
            home / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser",
        ]
    elif system == "Linux":
        candidates = [
            home / ".config" / "BraveSoftware" / "Brave-Browser",
        ]
    elif system == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates = [
            local_app_data / "BraveSoftware" / "Brave-Browser" / "User Data",
        ]
    else:
        candidates = []

    for candidate in candidates:
        if candidate.exists() and _list_profile_names(candidate):
            return candidate

    return None


def get_edge_user_data_dir() -> Optional[Path]:
    """Get the default Edge user data directory for the current platform."""
    system = platform.system()
    home = Path.home()

    if system == "Darwin":
        candidates = [
            home / "Library" / "Application Support" / "Microsoft Edge",
        ]
    elif system == "Linux":
        candidates = [
            home / ".config" / "microsoft-edge",
            home / ".config" / "microsoft-edge-beta",
            home / ".config" / "microsoft-edge-dev",
        ]
    elif system == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates = [
            local_app_data / "Microsoft" / "Edge" / "User Data",
        ]
    else:
        candidates = []

    for candidate in candidates:
        if candidate.exists() and _list_profile_names(candidate):
            return candidate

    return None


def get_browser_binary(browser: str) -> Optional[str]:
    system = platform.system()
    home = Path.home()
    browser = browser.lower()

    if system == "Darwin":
        candidates = {
            "chrome": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
            "chromium": ["/Applications/Chromium.app/Contents/MacOS/Chromium"],
            "brave": ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
            "edge": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
        }.get(browser, [])
    elif system == "Linux":
        candidates = {
            "chrome": ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/google-chrome-beta", "/usr/bin/google-chrome-unstable"],
            "chromium": ["/usr/bin/chromium", "/usr/bin/chromium-browser"],
            "brave": ["/usr/bin/brave-browser", "/usr/bin/brave-browser-beta", "/usr/bin/brave-browser-nightly"],
            "edge": ["/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable", "/usr/bin/microsoft-edge-beta", "/usr/bin/microsoft-edge-dev"],
        }.get(browser, [])
    elif system == "Windows":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates = {
            "chrome": [
                str(local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe"),
                "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            ],
            "chromium": [str(local_app_data / "Chromium" / "Application" / "chrome.exe")],
            "brave": [
                str(local_app_data / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"),
                "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
                "C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
            ],
            "edge": [
                str(local_app_data / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
                "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
            ],
        }.get(browser, [])
    else:
        candidates = []

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate

    return None


BROWSER_PROFILE_FINDERS = {
    "chrome": get_chrome_user_data_dir,
    "chromium": get_chrome_user_data_dir,
    "brave": get_brave_user_data_dir,
    "edge": get_edge_user_data_dir,
}

CHROMIUM_BROWSERS = tuple(BROWSER_PROFILE_FINDERS.keys())


NETSCAPE_COOKIE_HEADER = [
    "# Netscape HTTP Cookie File",
    "# https://curl.se/docs/http-cookies.html",
    "# This file was generated by ArchiveBox persona cookie extraction",
    "#",
    "# Format: domain\\tincludeSubdomains\\tpath\\tsecure\\texpiry\\tname\\tvalue",
    "",
]


def validate_persona_name(name: str) -> tuple[bool, str]:
    """Validate persona name to prevent path traversal."""
    if not name or not name.strip():
        return False, "Persona name cannot be empty"
    if "/" in name or "\\" in name:
        return False, "Persona name cannot contain path separators (/ or \\)"
    if ".." in name:
        return False, "Persona name cannot contain parent directory references (..)"
    if name.startswith("."):
        return False, "Persona name cannot start with a dot (.)"
    if "\x00" in name or "\n" in name or "\r" in name:
        return False, "Persona name contains invalid characters"
    return True, ""


def discover_local_browser_profiles() -> list[PersonaImportSource]:
    discovered: list[PersonaImportSource] = []

    for browser, finder in BROWSER_PROFILE_FINDERS.items():
        user_data_dir = finder()
        if not user_data_dir:
            continue

        browser_binary = get_browser_binary(browser)
        for profile_dir in _list_profile_names(user_data_dir):
            try:
                discovered.append(
                    resolve_browser_profile_source(
                        browser=browser,
                        user_data_dir=user_data_dir,
                        profile_dir=profile_dir,
                        browser_binary=browser_binary,
                    )
                )
            except ValueError:
                continue

    discovered.extend(discover_persona_template_profiles())

    return discovered


def discover_persona_template_profiles(personas_dir: Path | None = None) -> list[PersonaImportSource]:
    from archivebox.config.constants import CONSTANTS

    templates: list[PersonaImportSource] = []
    candidate_roots: list[Path] = []

    if personas_dir is not None:
        candidate_roots.append(personas_dir.expanduser())
    else:
        candidate_roots.extend(
            [
                CONSTANTS.PERSONAS_DIR.expanduser(),
                Path.home() / ".config" / "abx" / "personas",
            ]
        )

    seen_roots: set[Path] = set()
    for personas_root in candidate_roots:
        resolved_root = personas_root.resolve()
        if resolved_root in seen_roots:
            continue
        seen_roots.add(resolved_root)

        if not resolved_root.exists() or not resolved_root.is_dir():
            continue

        for persona_dir in sorted((path for path in resolved_root.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
            for candidate_dir_name in PERSONA_PROFILE_DIR_CANDIDATES:
                user_data_dir = persona_dir / candidate_dir_name
                if not user_data_dir.exists() or not user_data_dir.is_dir():
                    continue

                for profile_dir in _list_profile_names(user_data_dir):
                    try:
                        templates.append(
                            resolve_browser_profile_source(
                                browser="persona",
                                source_name=persona_dir.name,
                                user_data_dir=user_data_dir,
                                profile_dir=profile_dir,
                                browser_binary=get_browser_binary("chrome"),
                            )
                        )
                    except ValueError:
                        continue

    return templates


def resolve_browser_import_source(browser: str, profile_dir: str | None = None) -> PersonaImportSource:
    browser = browser.lower().strip()
    if browser not in BROWSER_PROFILE_FINDERS:
        supported = ", ".join(BROWSER_PROFILE_FINDERS)
        raise ValueError(f"Unknown browser: {browser}. Supported browsers: {supported}")

    user_data_dir = BROWSER_PROFILE_FINDERS[browser]()
    if not user_data_dir:
        raise ValueError(f"Could not find {browser} profile directory")

    chosen_profile = profile_dir or pick_default_profile_dir(user_data_dir)
    if not chosen_profile:
        raise ValueError(f"Could not find a profile in {user_data_dir}")

    return resolve_browser_profile_source(
        browser=browser,
        user_data_dir=user_data_dir,
        profile_dir=chosen_profile,
        browser_binary=get_browser_binary(browser),
    )


def resolve_browser_profile_source(
    browser: str,
    user_data_dir: Path,
    profile_dir: str,
    source_name: str | None = None,
    browser_binary: str | None = None,
) -> PersonaImportSource:
    resolved_root = user_data_dir.expanduser()
    if not resolved_root.is_absolute():
        resolved_root = resolved_root.resolve()
    if not resolved_root.exists():
        raise ValueError(f"Profile root does not exist: {resolved_root}")
    if not profile_dir.strip():
        raise ValueError("Profile directory name cannot be empty.")

    profile_path = resolved_root / profile_dir
    if not _looks_like_profile_dir(profile_path):
        raise ValueError(f"Profile directory does not look valid: {profile_path}")

    return PersonaImportSource(
        kind="browser-profile",
        browser=browser,
        source_name=source_name,
        user_data_dir=resolved_root,
        profile_dir=profile_dir,
        browser_binary=browser_binary,
    )


def resolve_custom_import_source(raw_value: str, profile_dir: str | None = None) -> PersonaImportSource:
    raw_value = raw_value.strip()
    if not raw_value:
        raise ValueError("Provide an absolute browser profile path or a CDP URL.")

    if _looks_like_cdp_url(raw_value):
        return PersonaImportSource(kind="cdp", cdp_url=raw_value)

    source_path = Path(raw_value).expanduser()
    if not source_path.is_absolute():
        raise ValueError("Custom browser path must be an absolute path.")
    if not source_path.exists():
        raise ValueError(f"Custom browser path does not exist: {source_path}")

    explicit_profile = profile_dir.strip() if profile_dir else ""
    if _looks_like_profile_dir(source_path):
        if explicit_profile and explicit_profile != source_path.name:
            raise ValueError("Profile name does not match the provided profile directory path.")
        return resolve_browser_profile_source(
            browser="custom",
            user_data_dir=source_path.parent.resolve(),
            profile_dir=source_path.name,
        )

    chosen_profile = explicit_profile or pick_default_profile_dir(source_path)
    if not chosen_profile:
        raise ValueError(
            "Could not find a Chromium profile in that directory. "
            "Provide an exact profile directory path or fill in the profile name field."
        )

    return resolve_browser_profile_source(
        browser="custom",
        user_data_dir=source_path.resolve(),
        profile_dir=chosen_profile,
    )


def pick_default_profile_dir(user_data_dir: Path) -> str | None:
    profiles = _list_profile_names(user_data_dir)
    if not profiles:
        return None
    if "Default" in profiles:
        return "Default"
    return profiles[0]


def import_persona_from_source(
    persona: "Persona",
    source: PersonaImportSource,
    *,
    copy_profile: bool = True,
    import_cookies: bool = True,
    capture_storage: bool = False,
) -> PersonaImportResult:
    persona.ensure_dirs()
    result = PersonaImportResult(source=source)

    persona_chrome_dir = Path(persona.CHROME_USER_DATA_DIR)
    cookies_file = persona.path / "cookies.txt"
    auth_file = persona.path / "auth.json"

    launch_user_data_dir: Path | None = None

    if source.kind == "browser-profile":
        if copy_profile and source.user_data_dir:
            resolved_source_root = source.user_data_dir.resolve()
            resolved_persona_root = persona_chrome_dir.resolve()
            if resolved_source_root == resolved_persona_root:
                result.warnings.append("Skipped profile copy because the selected source is already this persona's chrome_user_data directory.")
            else:
                copy_browser_user_data_dir(resolved_source_root, resolved_persona_root)
                persona.cleanup_chrome_profile(resolved_persona_root)
                result.profile_copied = True
            launch_user_data_dir = resolved_persona_root
        else:
            launch_user_data_dir = source.user_data_dir
    elif copy_profile:
        result.warnings.append("Profile copying is only available for local Chromium profile paths. CDP imports can only pull cookies and open-tab storage.")

    if source.kind == "cdp":
        export_success, auth_payload, export_message = export_browser_state(
            cdp_url=source.cdp_url,
            cookies_output_file=cookies_file if import_cookies else None,
            auth_output_file=auth_file if capture_storage else None,
        )
    else:
        export_success, auth_payload, export_message = export_browser_state(
            user_data_dir=launch_user_data_dir,
            profile_dir=source.profile_dir,
            chrome_binary=source.browser_binary,
            cookies_output_file=cookies_file if import_cookies else None,
            auth_output_file=auth_file if capture_storage else None,
        )

    if not export_success:
        result.warnings.append(export_message or "Browser import failed.")
        return result

    if import_cookies and cookies_file.exists():
        result.cookies_imported = True
    if capture_storage and auth_file.exists():
        result.storage_captured = True
    if _apply_imported_user_agent(persona, auth_payload):
        result.user_agent_imported = True

    return result


def copy_browser_user_data_dir(source_dir: Path, destination_dir: Path) -> None:
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(destination_dir, ignore_errors=True)
    shutil.copytree(
        source_dir,
        destination_dir,
        symlinks=True,
        ignore=shutil.ignore_patterns(*VOLATILE_PROFILE_COPY_PATTERNS),
    )


def export_browser_state(
    *,
    user_data_dir: Path | None = None,
    cdp_url: str | None = None,
    profile_dir: str | None = None,
    chrome_binary: str | None = None,
    cookies_output_file: Path | None = None,
    auth_output_file: Path | None = None,
) -> tuple[bool, dict | None, str]:
    if not user_data_dir and not cdp_url:
        return False, None, "Missing browser source."

    from abx_plugins import get_plugins_dir
    from archivebox.config.common import STORAGE_CONFIG

    state_script = Path(__file__).with_name("export_browser_state.js")
    if not state_script.exists():
        return False, None, f"Browser state export script not found at {state_script}"

    node_modules_dir = STORAGE_CONFIG.LIB_DIR / "npm" / "node_modules"
    chrome_plugin_dir = Path(get_plugins_dir()).resolve()

    env = os.environ.copy()
    env["NODE_MODULES_DIR"] = str(node_modules_dir)
    env["ARCHIVEBOX_ABX_PLUGINS_DIR"] = str(chrome_plugin_dir)

    if user_data_dir:
        env["CHROME_USER_DATA_DIR"] = str(user_data_dir)
    if cdp_url:
        env["CHROME_CDP_URL"] = cdp_url
        env["CHROME_IS_LOCAL"] = "false"
    if chrome_binary:
        env["CHROME_BINARY"] = str(chrome_binary)
    if profile_dir:
        extra_arg = f"--profile-directory={profile_dir}"
        existing_extra = env.get("CHROME_ARGS_EXTRA", "").strip()
        args_list: list[str] = []
        if existing_extra:
            if existing_extra.startswith("["):
                try:
                    parsed = json.loads(existing_extra)
                    if isinstance(parsed, list):
                        args_list.extend(str(x) for x in parsed)
                except Exception:
                    args_list.extend([s.strip() for s in existing_extra.split(",") if s.strip()])
            else:
                args_list.extend([s.strip() for s in existing_extra.split(",") if s.strip()])
        args_list.append(extra_arg)
        env["CHROME_ARGS_EXTRA"] = json.dumps(args_list)

    temp_dir: Path | None = None
    tmp_cookies_file: Path | None = None
    tmp_auth_file: Path | None = None

    if cookies_output_file and cookies_output_file.exists():
        temp_dir = Path(tempfile.mkdtemp(prefix="ab_browser_state_"))
        tmp_cookies_file = temp_dir / "cookies.txt"
        env["COOKIES_OUTPUT_FILE"] = str(tmp_cookies_file)
    elif cookies_output_file:
        env["COOKIES_OUTPUT_FILE"] = str(cookies_output_file)

    if auth_output_file and auth_output_file.exists():
        temp_dir = temp_dir or Path(tempfile.mkdtemp(prefix="ab_browser_state_"))
        tmp_auth_file = temp_dir / "auth.json"
        env["AUTH_STORAGE_OUTPUT_FILE"] = str(tmp_auth_file)
    elif auth_output_file:
        env["AUTH_STORAGE_OUTPUT_FILE"] = str(auth_output_file)
    else:
        temp_dir = temp_dir or Path(tempfile.mkdtemp(prefix="ab_browser_state_"))
        tmp_auth_file = temp_dir / "auth.json"
        env["AUTH_STORAGE_OUTPUT_FILE"] = str(tmp_auth_file)

    try:
        result = subprocess.run(
            ["node", str(state_script)],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, None, "Browser state export timed out."
    except FileNotFoundError:
        return False, None, "Node.js was not found, so ArchiveBox could not extract browser state."
    except Exception as err:
        return False, None, f"Browser state export failed: {err}"

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip() or "Browser state export failed."
        return False, None, message

    auth_payload: dict | None = None
    if cookies_output_file and tmp_cookies_file and tmp_cookies_file.exists():
        _merge_netscape_cookies(cookies_output_file, tmp_cookies_file)
    if auth_output_file and tmp_auth_file and tmp_auth_file.exists():
        _merge_auth_storage(auth_output_file, tmp_auth_file)
        auth_payload = _load_auth_storage(tmp_auth_file)
    elif auth_output_file and auth_output_file.exists():
        auth_payload = _load_auth_storage(auth_output_file)
    elif tmp_auth_file and tmp_auth_file.exists():
        auth_payload = _load_auth_storage(tmp_auth_file)

    if temp_dir and temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    return True, auth_payload, (result.stderr or result.stdout or "").strip()


def _list_profile_names(user_data_dir: Path) -> list[str]:
    if not user_data_dir.exists() or not user_data_dir.is_dir():
        return []

    profiles: list[str] = []
    for child in sorted(user_data_dir.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir():
            continue
        if child.name == "System Profile":
            continue
        if child.name == "Default" or child.name.startswith("Profile ") or child.name.startswith("Guest Profile"):
            if _looks_like_profile_dir(child):
                profiles.append(child.name)
                continue
        if _looks_like_profile_dir(child):
            profiles.append(child.name)
    return profiles


def _looks_like_profile_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False

    marker_paths = (
        path / "Preferences",
        path / "History",
        path / "Cookies",
        path / "Network" / "Cookies",
        path / "Local Storage",
        path / "Session Storage",
    )

    if any(marker.exists() for marker in marker_paths):
        return True

    return any(path.name == prefix or path.name.startswith(prefix) for prefix in BROWSER_PROFILE_DIR_NAMES)


def _looks_like_cdp_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"ws", "wss", "http", "https"} and bool(parsed.netloc)


def _parse_netscape_cookies(path: Path) -> dict[tuple[str, str, str], tuple[str, str, str, str, str, str, str]]:
    cookies: dict[tuple[str, str, str], tuple[str, str, str, str, str, str, str]] = {}
    if not path.exists():
        return cookies

    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, include_subdomains, cookie_path, secure, expiry, name, value = parts[:7]
        cookies[(domain, cookie_path, name)] = (domain, include_subdomains, cookie_path, secure, expiry, name, value)
    return cookies


def _write_netscape_cookies(
    path: Path,
    cookies: dict[tuple[str, str, str], tuple[str, str, str, str, str, str, str]],
) -> None:
    lines = list(NETSCAPE_COOKIE_HEADER)
    for cookie in cookies.values():
        lines.append("\t".join(cookie))
    path.write_text("\n".join(lines) + "\n")


def _merge_netscape_cookies(existing_file: Path, new_file: Path) -> None:
    existing = _parse_netscape_cookies(existing_file)
    new = _parse_netscape_cookies(new_file)
    existing.update(new)
    _write_netscape_cookies(existing_file, existing)


def _merge_auth_storage(existing_file: Path, new_file: Path) -> None:
    existing_payload = _load_auth_storage(existing_file)
    new_payload = _load_auth_storage(new_file)

    existing_local = existing_payload.setdefault("localStorage", {})
    existing_session = existing_payload.setdefault("sessionStorage", {})

    for origin, payload in (new_payload.get("localStorage") or {}).items():
        existing_local[origin] = payload
    for origin, payload in (new_payload.get("sessionStorage") or {}).items():
        existing_session[origin] = payload

    cookies = _merge_cookie_dicts(existing_payload.get("cookies") or [], new_payload.get("cookies") or [])

    merged = {
        **existing_payload,
        **new_payload,
        "cookies": cookies,
        "localStorage": existing_local,
        "sessionStorage": existing_session,
        "user_agent": new_payload.get("user_agent") or existing_payload.get("user_agent") or "",
    }
    existing_file.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")


def _load_auth_storage(path: Path) -> dict:
    if not path.exists():
        return {
            "TYPE": "auth",
            "cookies": [],
            "localStorage": {},
            "sessionStorage": {},
        }
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {
            "TYPE": "auth",
            "cookies": [],
            "localStorage": {},
            "sessionStorage": {},
        }
    if not isinstance(payload, dict):
        return {
            "TYPE": "auth",
            "cookies": [],
            "localStorage": {},
            "sessionStorage": {},
        }
    return payload


def _merge_cookie_dicts(existing: list[dict], new: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str, str], dict] = {}
    for cookie in existing:
        key = (str(cookie.get("domain") or ""), str(cookie.get("path") or "/"), str(cookie.get("name") or ""))
        merged[key] = cookie
    for cookie in new:
        key = (str(cookie.get("domain") or ""), str(cookie.get("path") or "/"), str(cookie.get("name") or ""))
        merged[key] = cookie
    return list(merged.values())


def _apply_imported_user_agent(persona: "Persona", auth_payload: dict | None) -> bool:
    if not auth_payload:
        return False

    user_agent = str(auth_payload.get("user_agent") or "").strip()
    if not user_agent:
        return False

    config = dict(persona.config or {})
    if config.get("USER_AGENT") == user_agent:
        return False

    config["USER_AGENT"] = user_agent
    persona.config = config
    persona.save(update_fields=["config"])
    return True
