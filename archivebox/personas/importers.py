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
import sqlite3
import time
from http.cookiejar import MozillaCookieJar
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
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
    # Chromium/macOS atomic-write staging files (e.g.
    # .com.brave.Browser.TransportSecurity.Ze7UBU) disappear after rename.
    ".*.??????",
    "Cache",
    "Code Cache",
    "GPUCache",
    "ShaderCache",
    "Crashpad",
    "BrowserMetrics",
    "BrowserMetrics-spare.pma",
    "RunningChromeVersion",
    "DevToolsActivePort",
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
    "Sessions",
    "Sessions_Encrypted",
    "Current Session",
    "Current Tabs",
    "Last Session",
    "Last Tabs",
)

PERSONA_PROFILE_DIR_CANDIDATES = (
    "chrome_profile",
    "chrome_user_data",
)


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _iter_children(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _is_copyable_profile_entry(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        if path.is_dir():
            return os.access(path, os.R_OK | os.X_OK)
        return os.access(path, os.R_OK)
    except OSError:
        return False


def profile_copy_ignore(src: str, names: list[str]) -> set[str]:
    ignored = set(shutil.ignore_patterns(*VOLATILE_PROFILE_COPY_PATTERNS)(src, names))
    src_path = Path(src)
    for name in names:
        if name in ignored:
            continue
        if not _is_copyable_profile_entry(src_path / name):
            # Chrome can leave generated profile components unreadable when a
            # previous run used a different runtime uid, a mounted profile came
            # from the host, or Chrome tightened permissions on cache/model
            # directories. Those entries are not required to launch a cloned
            # profile, and letting copytree abort here prevents the crawl from
            # even creating its first Snapshot.
            ignored.add(name)
    return ignored


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
        binary_suffix = f"Using {self.browser_binary}" if self.browser_binary else "Chromium resolved by abxpkg"
        return format_html(
            '<span class="abx-profile-option"><strong>{}</strong><span class="abx-profile-option__meta">{}</span><code>{}</code></span>',
            self.display_label,
            binary_suffix,
            path_str,
        )

    @classmethod
    def from_choice_value(cls, value: str) -> PersonaImportSource:
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
    cookie_count: int = 0
    storage_captured: bool = False
    user_agent_imported: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def did_work(self) -> bool:
        return self.profile_copied or self.cookies_imported or self.storage_captured or self.user_agent_imported


def get_chrome_user_data_dir() -> Path | None:
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


def get_brave_user_data_dir() -> Path | None:
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


def get_edge_user_data_dir() -> Path | None:
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

        for profile_dir in _list_profile_names(user_data_dir):
            try:
                discovered.append(
                    resolve_browser_profile_source(
                        browser=browser,
                        user_data_dir=user_data_dir,
                        profile_dir=profile_dir,
                    ),
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
            ],
        )

    seen_roots: set[Path] = set()
    for personas_root in candidate_roots:
        resolved_root = personas_root.resolve()
        if resolved_root in seen_roots:
            continue
        seen_roots.add(resolved_root)

        if not _path_is_dir(resolved_root):
            continue

        for persona_dir in sorted(
            (path for path in _iter_children(resolved_root) if _path_is_dir(path)),
            key=lambda path: path.name.lower(),
        ):
            for candidate_dir_name in PERSONA_PROFILE_DIR_CANDIDATES:
                user_data_dir = persona_dir / candidate_dir_name
                if not _path_is_dir(user_data_dir):
                    continue

                for profile_dir in _list_profile_names(user_data_dir):
                    try:
                        templates.append(
                            resolve_browser_profile_source(
                                browser="persona",
                                source_name=persona_dir.name,
                                user_data_dir=user_data_dir,
                                profile_dir=profile_dir,
                            ),
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
        raise ValueError(
            f"Could not find {browser} profile directory. Use --source /path/to/browser-data. "
            "For Docker on macOS/Windows, import on the host into the shared data directory first.",
        )

    chosen_profile = profile_dir or pick_default_profile_dir(user_data_dir)
    if not chosen_profile:
        raise ValueError(f"Could not find a profile in {user_data_dir}")

    return resolve_browser_profile_source(
        browser=browser,
        user_data_dir=user_data_dir,
        profile_dir=chosen_profile,
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
    if Path(profile_dir).name != profile_dir or profile_dir in {".", ".."}:
        raise ValueError("Profile must be a directory name within the source browser root.")
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
            "Provide an exact profile directory path or fill in the profile name field.",
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


def resolve_source_browser_binary(source: PersonaImportSource) -> str:
    """Use the originating browser so OS-protected cookies use the correct keychain."""
    if source.browser_binary:
        return str(Path(source.browser_binary).expanduser().resolve())
    names = {
        "chrome": ("Google Chrome", "google-chrome"),
        "chromium": ("Chromium", "chromium"),
        "brave": ("Brave Browser", "brave-browser"),
        "edge": ("Microsoft Edge", "microsoft-edge"),
    }
    app, executable = names.get(source.browser, ("", ""))
    candidates = []
    if platform.system() == "Darwin" and app:
        candidates = [
            Path("/Applications") / f"{app}.app/Contents/MacOS/{app}",
            Path.home() / f"Applications/{app}.app/Contents/MacOS/{app}",
        ]
    elif platform.system() == "Windows":
        relative = {
            "chrome": "Google/Chrome/Application/chrome.exe",
            "edge": "Microsoft/Edge/Application/msedge.exe",
            "brave": "BraveSoftware/Brave-Browser/Application/brave.exe",
            "chromium": "Chromium/Application/chrome.exe",
        }.get(source.browser)
        if relative:
            candidates = [
                Path(os.environ[root]) / relative for root in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)") if os.environ.get(root)
            ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    if executable and (found := shutil.which(executable)):
        return found
    raise ValueError(
        f"Source {source.browser} browser executable not found. Use --browser-binary with the originating Chromium browser. "
        "For Docker, run persona create --import on the browser's host into the shared data directory first: "
        "the container cannot decrypt cookies using the host's macOS Keychain or Windows credentials.",
    )


def import_persona_from_source(
    persona: Persona,
    source: PersonaImportSource,
    *,
    copy_profile: bool = True,
    import_cookies: bool = True,
    capture_storage: bool = False,
) -> PersonaImportResult:
    # Stage all work before replacing an existing, working identity.
    persona.ensure_dirs()
    result = PersonaImportResult(source=source)
    expected_cookies = 0
    browser_binary = None
    native_cookie_browsers = {"chrome", "chromium", "brave", "edge", "vivaldi", "opera", "opera_gx"}
    # browser-cookie3 needs a desktop D-Bus session on Linux. In a headless
    # environment, let the originating browser decode its own profile instead.
    has_native_cookie_decoder = platform.system() != "Linux" or bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
    native_cookie_import = source.kind == "browser-profile" and source.browser in native_cookie_browsers and has_native_cookie_decoder
    if source.kind == "browser-profile" and (import_cookies or capture_storage):
        if not native_cookie_import:
            browser_binary = resolve_source_browser_binary(source)
        for cookie_db in (source.profile_path / "Network" / "Cookies", source.profile_path / "Cookies"):
            if cookie_db.is_file():
                with sqlite3.connect(f"{cookie_db.as_uri()}?mode=ro", uri=True) as conn:
                    expected_cookies = conn.execute(
                        "SELECT COUNT(*) FROM cookies WHERE expires_utc = 0 OR expires_utc > ?",
                        (int((time.time() + 11644473600) * 1_000_000),),
                    ).fetchone()[0]
                break
    with tempfile.TemporaryDirectory(prefix=".import-", dir=persona.path.parent) as tmp:
        stage = Path(tmp)
        staged_profile = stage / "chrome_profile"
        if source.kind == "browser-profile":
            assert source.user_data_dir and source.profile_path
            if copy_profile or import_cookies or capture_storage:
                staged_profile.mkdir()
                # Only the selected profile belongs to this persona. Normalize its
                # name so downstream Chromium launches always select it.
                copy_browser_user_data_dir(source.profile_path, staged_profile / "Default")
                local_state = source.user_data_dir / "Local State"
                if local_state.exists():
                    state = json.loads(local_state.read_text())
                    profile_state = state.setdefault("profile", {})
                    profile_state["last_used"] = "Default"
                    profile_state["last_active_profiles"] = ["Default"]
                    info = profile_state.get("info_cache", {}).get(source.profile_dir)
                    profile_state["info_cache"] = {"Default": info} if info else {}
                    (staged_profile / "Local State").write_text(json.dumps(state))
                persona.cleanup_chrome_profile(staged_profile)
                result.profile_copied = copy_profile
        elif copy_profile:
            result.warnings.append(
                "CDP imports capture cookies and open-tab storage, not browser settings. Use --source for a full profile import.",
            )

        if import_cookies or capture_storage:
            if native_cookie_import:
                auth_payload = export_profile_cookies(source, staged_profile, stage)
                success, message = True, ""
            else:
                # Custom browsers and headless Linux use the originating browser.
                # Desktop imports use their OS decoder without launching or probing.
                launch_profile = stage / "export_profile"
                if source.kind == "browser-profile":
                    copy_browser_user_data_dir(staged_profile, launch_profile)
                success, auth_payload, message = export_browser_state(
                    user_data_dir=launch_profile if source.kind == "browser-profile" else None,
                    cdp_url=source.cdp_url,
                    profile_dir="Default" if source.kind == "browser-profile" else None,
                    chrome_binary=browser_binary,
                    cookies_output_file=stage / "cookies.txt" if import_cookies else None,
                    auth_output_file=stage / "auth.json",
                )
            if not success:
                raise ValueError(message or "Browser state export failed; persona was not replaced.")
            if expected_cookies and not (auth_payload or {}).get("cookies"):
                raise ValueError(
                    "The source has cookies but the browser exported none. Run the import on the source host "
                    "with the original browser and unlock its OS keychain; the existing persona was not replaced.",
                )
            if import_cookies:
                result.cookies_imported = True
                result.cookie_count = len((auth_payload or {}).get("cookies", []))
            if capture_storage:
                result.storage_captured = True
            # Keep full CDP cookie attributes (sameSite, httpOnly, partition keys)
            # as well as cookies.txt for non-browser extractors.
            result.user_agent_imported = _apply_imported_user_agent(persona, auth_payload)

        if result.profile_copied:
            target = Path(persona.CHROME_USER_DATA_DIR)
            if target.exists():
                shutil.rmtree(target)
            staged_profile.rename(target)
        for filename in ("cookies.txt", "auth.json"):
            exported = stage / filename
            if exported.exists():
                exported.chmod(0o600)
                exported.replace(persona.path / filename)
    return result


def export_profile_cookies(source: PersonaImportSource, staged_profile: Path, output: Path) -> dict:
    """Decode with the host keychain, never by starting the user's browser."""
    import browser_cookie3

    payload = {"TYPE": "auth", "cookies": [], "localStorage": {}, "sessionStorage": {}}
    jar = MozillaCookieJar(str(output / "cookies.txt"))
    assert source.profile_path
    for relative in (Path("Network/Cookies"), Path("Cookies")):
        original = source.profile_path / relative
        if not original.is_file():
            continue
        database = staged_profile / "Default" / relative
        for suffix in ("", "-wal", "-shm"):
            database.with_name(database.name + suffix).unlink(missing_ok=True)
        # SQLite backup includes committed WAL data even while the browser is open.
        with sqlite3.connect(f"{original.as_uri()}?mode=ro", uri=True) as reader:
            with sqlite3.connect(database) as writer:
                reader.backup(writer)
        try:
            cookies = getattr(browser_cookie3, source.browser)(
                cookie_file=str(database),
                key_file=str(staged_profile / "Local State"),
            )
        except Exception as err:
            raise ValueError(
                "Could not decrypt browser cookies. Run the import as your desktop user on the browser host "
                "with its OS keychain unlocked. Mounting macOS/Windows browser files into Linux does not provide "
                "the decryption keys. The existing persona was not replaced.",
            ) from err
        with sqlite3.connect(database) as connection:
            connection.row_factory = sqlite3.Row
            columns = {row[1] for row in connection.execute("PRAGMA table_info(cookies)")}
            metadata_columns = [
                name
                for name in ("host_key", "path", "name", "samesite", "top_frame_site_key", "has_cross_site_ancestor")
                if name in columns
            ]
            rows = {
                (row["host_key"], row["path"], row["name"]): dict(row)
                for row in connection.execute("SELECT " + ", ".join(metadata_columns) + " FROM cookies")
            }
        for cookie in cookies:
            if cookie.is_expired():
                continue
            jar.set_cookie(cookie)
            item = {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": bool(cookie.secure),
                "httpOnly": cookie.has_nonstandard_attr("HTTPOnly"),
            }
            if cookie.expires:
                item["expires"] = cookie.expires
            row = rows.get((cookie.domain, cookie.path, cookie.name), {})
            same_site = {0: "None", 1: "Lax", 2: "Strict"}.get(row.get("samesite"))
            if same_site:
                item["sameSite"] = same_site
            if row.get("top_frame_site_key"):
                item["partitionKey"] = {
                    "topLevelSite": row["top_frame_site_key"],
                    "hasCrossSiteAncestor": bool(row.get("has_cross_site_ancestor", False)),
                }
            payload["cookies"].append(item)
        break
    jar.save(ignore_discard=True, ignore_expires=False)
    (output / "auth.json").write_text(json.dumps(payload) + "\n")
    return payload


def copy_browser_user_data_dir(source_dir: Path, destination_dir: Path) -> None:
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(destination_dir, ignore_errors=True)
    shutil.copytree(
        source_dir,
        destination_dir,
        symlinks=True,
        ignore=profile_copy_ignore,
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
    from archivebox.config.common import get_config

    state_script = Path(__file__).with_name("export_browser_state.js")
    if not state_script.exists():
        return False, None, f"Browser state export script not found at {state_script}"

    chrome_plugin_dir = Path(get_plugins_dir()).resolve()
    chrome_config = chrome_plugin_dir / "chrome" / "config.json"

    env = os.environ.copy()
    dependency_config = json.loads(chrome_config.read_text())
    dependency_config["required_binaries"] = [dep for dep in dependency_config["required_binaries"] if dep["name"] != "{CHROME_BINARY}"]
    dependency_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    with dependency_file:
        json.dump(dependency_config, dependency_file)
    try:
        dependency_env = subprocess.run(
            [
                str(Path(sys.executable).with_name("abxpkg")),
                "env",
                "--install",
                "--json",
                f"--lib={get_config().ABXPKG_LIB_DIR}",
                f"--deps-from={dependency_file.name}:required_binaries",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        Path(dependency_file.name).unlink()
    if dependency_env.returncode != 0:
        return False, None, dependency_env.stderr.strip() or "abxpkg could not resolve browser export dependencies."
    try:
        resolved_env = json.loads(dependency_env.stdout)
    except json.JSONDecodeError:
        return False, None, "abxpkg returned an invalid browser dependency environment."
    if not isinstance(resolved_env, dict):
        return False, None, "abxpkg returned an invalid browser dependency environment."
    abxpkg_lib_dir = get_config().ABXPKG_LIB_DIR
    node_projection = abxpkg_lib_dir / "env" / "bin" / "node"
    if not node_projection.is_symlink() or not os.access(node_projection, os.X_OK):
        return False, None, f"abxpkg did not resolve Node.js into {node_projection}."
    env.update({str(key): str(value) for key, value in resolved_env.items()})
    if chrome_binary:
        env["CHROME_BINARY"] = chrome_binary
    env["NODE_MODULES_DIR"] = str(abxpkg_lib_dir / "pnpm" / "packages" / "chrome" / "node_modules")
    env["NODE_BINARY"] = str(node_projection)
    env["ARCHIVEBOX_ABX_PLUGINS_DIR"] = str(chrome_plugin_dir)

    if user_data_dir:
        env["CHROME_USER_DATA_DIR"] = str(user_data_dir)
    if cdp_url:
        env["CHROME_CDP_URL"] = cdp_url
        env["CHROME_IS_LOCAL"] = "false"
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
            [str(node_projection), str(state_script)],
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
    if not _path_is_dir(user_data_dir):
        return []

    profiles: list[str] = []
    for child in sorted(_iter_children(user_data_dir), key=lambda path: path.name.lower()):
        if not _path_is_dir(child):
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
    if not _path_is_dir(path):
        return False

    marker_paths = (
        path / "Preferences",
        path / "History",
        path / "Cookies",
        path / "Network" / "Cookies",
        path / "Local Storage",
        path / "Session Storage",
    )

    if any(_path_exists(marker) for marker in marker_paths):
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


def _apply_imported_user_agent(persona: Persona, auth_payload: dict | None) -> bool:
    if not auth_payload:
        return False

    user_agent = str(auth_payload.get("user_agent") or "").strip().replace("HeadlessChrome/", "Chrome/")
    if not user_agent:
        return False

    config = dict(persona.config or {})
    if config.get("USER_AGENT") == user_agent:
        return False

    config["USER_AGENT"] = user_agent
    persona.config = config
    persona.save(update_fields=["config"])
    return True
