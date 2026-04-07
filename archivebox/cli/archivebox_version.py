#!/usr/bin/env python3

__package__ = "archivebox.cli"

import sys
import os
import platform
from pathlib import Path
from collections.abc import Iterable

import rich_click as click

from archivebox.misc.util import docstring, enforce_types


def _format_binary_abspath(
    abspath: str,
    *,
    pwd: Path,
    lib_dir: Path,
    personas_dir: Path,
    home: Path,
) -> str:
    path = Path(abspath).expanduser()
    try:
        normalized = path.resolve(strict=False)
    except Exception:
        normalized = path

    machine = platform.machine().lower()
    system = platform.system().lower()
    arch_scope = f"{machine}-{system}"

    candidate_bases: tuple[tuple[Path, str], ...] = (
        (pwd, "./"),
        (lib_dir, "LIB_DIR/"),
        (Path(os.environ.get("LIB_DIR", "")), "LIB_DIR/") if os.environ.get("LIB_DIR") else (Path(), ""),
        (personas_dir, "PERSONAS_DIR/"),
        (Path(os.environ.get("PERSONAS_DIR", "")), "PERSONAS_DIR/") if os.environ.get("PERSONAS_DIR") else (Path(), ""),
        (home / ".config" / "abx" / "lib" / arch_scope, "LIB_DIR/"),
        (home / ".config" / "abx" / "lib", "LIB_DIR/"),
        (home / ".config" / "abx" / "personas", "PERSONAS_DIR/"),
        (home, "~/"),
    )

    for base, prefix in candidate_bases:
        if not prefix:
            continue
        for candidate in (base, base.resolve(strict=False)):
            try:
                relative = normalized.relative_to(candidate)
            except ValueError:
                continue

            relative_str = relative.as_posix()
            if prefix == "./":
                return "." if not relative_str else f"./{relative_str}"
            if prefix == "LIB_DIR/":
                return "LIB_DIR" if not relative_str else f"LIB_DIR/{relative_str}"
            if prefix == "PERSONAS_DIR/":
                return "PERSONAS_DIR" if not relative_str else f"PERSONAS_DIR/{relative_str}"
            return "~" if not relative_str else f"~/{relative_str}"

    return normalized.as_posix()


def _render_binary_abspath(abspath: str):
    from rich.text import Text

    if abspath.startswith("LIB_DIR/"):
        return Text.assemble(("LIB_DIR", "bright_blue"), (abspath.removeprefix("LIB_DIR"), "green"))
    if abspath == "LIB_DIR":
        return Text("LIB_DIR", style="bright_blue")
    if abspath.startswith("PERSONAS_DIR/"):
        return Text.assemble(("PERSONAS_DIR", "medium_purple"), (abspath.removeprefix("PERSONAS_DIR"), "green"))
    if abspath == "PERSONAS_DIR":
        return Text("PERSONAS_DIR", style="medium_purple")
    if abspath.startswith("~/"):
        return Text.assemble(("~", "cyan"), (abspath.removeprefix("~"), "green"))
    if abspath == "~":
        return Text("~", style="cyan")
    if abspath.startswith("./"):
        return Text.assemble((".", "cyan"), (abspath.removeprefix("."), "green"))
    if abspath == ".":
        return Text(".", style="cyan")
    return Text(abspath, style="green")


@enforce_types
def version(
    quiet: bool = False,
    binaries: Iterable[str] = (),
) -> list[str]:
    """Print the ArchiveBox version, debug metadata, and installed dependency versions"""

    # fast path for just getting the version and exiting, dont do any slower imports
    from archivebox.config.version import VERSION

    print(VERSION)
    if quiet or "--version" in sys.argv:
        return []

    from rich.panel import Panel
    from rich.console import Console

    from archivebox.config import CONSTANTS
    from archivebox.config.version import get_COMMIT_HASH, get_BUILD_TIME
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, RUNNING_AS_UID, RUNNING_AS_GID, IN_DOCKER
    from archivebox.config.paths import get_data_locations, get_code_locations
    from archivebox.config.common import SHELL_CONFIG, STORAGE_CONFIG, SEARCH_BACKEND_CONFIG
    from archivebox.misc.logging_util import printable_folder_status
    from archivebox.config.configset import get_config

    console = Console()
    prnt = console.print

    # Check if LDAP is enabled (simple config lookup)
    config = get_config()
    LDAP_ENABLED = config.get("LDAP_ENABLED", False)

    p = platform.uname()
    COMMIT_HASH = get_COMMIT_HASH()
    prnt(
        f"[dark_green]ArchiveBox[/dark_green] [dark_goldenrod]v{CONSTANTS.VERSION}[/dark_goldenrod]",
        f"COMMIT_HASH={COMMIT_HASH[:7] if COMMIT_HASH else 'unknown'}",
        f"BUILD_TIME={get_BUILD_TIME()}",
    )
    prnt(
        f"IN_DOCKER={IN_DOCKER}",
        f"IN_QEMU={SHELL_CONFIG.IN_QEMU}",
        f"ARCH={p.machine}",
        f"OS={p.system}",
        f"PLATFORM={platform.platform()}",
        f"PYTHON={sys.implementation.name.title()}" + (" (venv)" if CONSTANTS.IS_INSIDE_VENV else ""),
    )

    try:
        OUTPUT_IS_REMOTE_FS = get_data_locations().DATA_DIR.is_mount or get_data_locations().ARCHIVE_DIR.is_mount
    except Exception:
        OUTPUT_IS_REMOTE_FS = False

    try:
        DATA_DIR_STAT = CONSTANTS.DATA_DIR.stat()
        prnt(
            f"EUID={os.geteuid()}:{os.getegid()} UID={RUNNING_AS_UID}:{RUNNING_AS_GID} PUID={ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}",
            f"FS_UID={DATA_DIR_STAT.st_uid}:{DATA_DIR_STAT.st_gid}",
            f"FS_PERMS={STORAGE_CONFIG.OUTPUT_PERMISSIONS}",
            f"FS_ATOMIC={STORAGE_CONFIG.ENFORCE_ATOMIC_WRITES}",
            f"FS_REMOTE={OUTPUT_IS_REMOTE_FS}",
        )
    except Exception:
        prnt(
            f"EUID={os.geteuid()}:{os.getegid()} UID={RUNNING_AS_UID}:{RUNNING_AS_GID} PUID={ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}",
        )

    prnt(
        f"DEBUG={SHELL_CONFIG.DEBUG}",
        f"IS_TTY={SHELL_CONFIG.IS_TTY}",
        f"SUDO={CONSTANTS.IS_ROOT}",
        f"ID={CONSTANTS.MACHINE_ID}:{CONSTANTS.COLLECTION_ID}",
        f"SEARCH_BACKEND={SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE}",
        f"LDAP={LDAP_ENABLED}",
    )
    prnt()

    if not (os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK) and os.access(CONSTANTS.CONFIG_FILE, os.R_OK)):
        PANEL_TEXT = "\n".join(
            (
                "",
                "[violet]Hint:[/violet] [green]cd[/green] into a collection [blue]DATA_DIR[/blue] and run [green]archivebox version[/green] again...",
                "      [grey53]OR[/grey53] run [green]archivebox init[/green] to create a new collection in the current dir.",
                "",
                "      [i][grey53](this is [red]REQUIRED[/red] if you are opening a Github Issue to get help)[/grey53][/i]",
                "",
            ),
        )
        prnt(
            Panel(
                PANEL_TEXT,
                expand=False,
                border_style="grey53",
                title="[red]:exclamation: No collection [blue]DATA_DIR[/blue] is currently active[/red]",
                subtitle="Full version info is only available when inside a collection [light_slate_blue]DATA DIR[/light_slate_blue]",
            ),
        )
        prnt()
        return []

    prnt("[pale_green1][i] Binary Dependencies:[/pale_green1]")
    failures = []

    # Setup Django before importing models
    try:
        from archivebox.config.django import setup_django

        setup_django()

        from archivebox.machine.models import Machine, Binary

        machine = Machine.current()

        if isinstance(binaries, str):
            requested_names = {name.strip() for name in binaries.split(",") if name.strip()}
        else:
            requested_names = {name for name in (binaries or ()) if name}

        db_binaries: dict[str, Binary] = {}
        for binary in Binary.objects.filter(machine=machine).order_by("name", "-modified_at"):
            db_binaries.setdefault(binary.name, binary)

        all_binary_names = sorted(requested_names or set(db_binaries.keys()))

        if not all_binary_names:
            prnt("", "[grey53]No binaries detected. Run [green]archivebox install[/green] to detect dependencies.[/grey53]")
        else:
            any_available = False
            compact_paths = console.is_terminal
            for name in all_binary_names:
                if requested_names and name not in requested_names:
                    continue

                installed = db_binaries.get(name)
                if installed and installed.is_valid:
                    display_name = Path(name).expanduser().name if ("/" in name or name.startswith("~")) else name
                    display_path = (
                        _format_binary_abspath(
                            installed.abspath,
                            pwd=Path.cwd(),
                            lib_dir=STORAGE_CONFIG.LIB_DIR,
                            personas_dir=Path.home() / ".config" / "abx" / "personas",
                            home=Path.home(),
                        )
                        if compact_paths
                        else installed.abspath
                    )
                    rendered_path = _render_binary_abspath(display_path) if compact_paths else display_path
                    version_str = (installed.version or "unknown")[:15]
                    provider = (installed.binprovider or "env")[:8]
                    prnt(
                        "",
                        "[green]√[/green]",
                        "",
                        display_name.ljust(18),
                        version_str.ljust(16),
                        provider.ljust(8),
                        rendered_path,
                        overflow="ignore",
                        crop=False,
                    )
                    any_available = True
                    continue

                status = (
                    "[grey53]not recorded[/grey53]" if name in requested_names and installed is None else "[grey53]not installed[/grey53]"
                )
                prnt("", "[red]X[/red]", "", name.ljust(18), status, overflow="ignore", crop=False)
                failures.append(name)

            if not any_available:
                prnt("", "[grey53]No binaries detected. Run [green]archivebox install[/green] to detect dependencies.[/grey53]")

        # Show hint if no binaries are installed yet
        has_any_installed = Binary.objects.filter(machine=machine).exclude(abspath="").exists()
        if not has_any_installed:
            prnt()
            prnt("", "[grey53]Run [green]archivebox install[/green] to detect and install dependencies.[/grey53]")

    except Exception as e:
        # Handle database errors gracefully (locked, missing, etc.)
        prnt()
        prnt("", f"[yellow]Warning: Could not query binaries from database: {e}[/yellow]")
        prnt("", "[grey53]Run [green]archivebox init[/green] and [green]archivebox install[/green] to set up dependencies.[/grey53]")

    if not binaries:
        # Show code and data locations
        prnt()
        prnt("[deep_sky_blue3][i] Code locations:[/deep_sky_blue3]")
        try:
            for name, path in get_code_locations().items():
                if isinstance(name, str) and isinstance(path, dict):
                    prnt(printable_folder_status(name, path), overflow="ignore", crop=False)
        except Exception as e:
            prnt(f"  [red]Error getting code locations: {e}[/red]")

        prnt()
        if os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK) or os.access(CONSTANTS.CONFIG_FILE, os.R_OK):
            prnt("[bright_yellow][i] Data locations:[/bright_yellow]")
            try:
                for name, path in get_data_locations().items():
                    if isinstance(name, str) and isinstance(path, dict):
                        prnt(printable_folder_status(name, path), overflow="ignore", crop=False)
            except Exception as e:
                prnt(f"  [red]Error getting data locations: {e}[/red]")

            try:
                from archivebox.misc.checks import check_data_dir_permissions

                check_data_dir_permissions()
            except Exception:
                pass
        else:
            prnt()
            prnt("[red][i] Data locations:[/red] (not in a data directory)")

    prnt()

    if failures:
        prnt("[red]Error:[/red] [yellow]Failed to detect the following binaries:[/yellow]")
        prnt(f"      [red]{', '.join(failures)}[/red]")
        prnt()
        prnt("[violet]Hint:[/violet] To install missing binaries automatically, run:")
        prnt("      [green]archivebox install[/green]")
        prnt()
    return failures


@click.command()
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Only print ArchiveBox version number and nothing else. (equivalent to archivebox --version)",
)
@click.option(
    "--binaries",
    "-b",
    help="Select binaries to detect DEFAULT=curl,wget,git,yt-dlp,chrome,single-file,readability-extractor,postlight-parser,... (all)",
)
@docstring(version.__doc__)
def main(**kwargs):
    failures = version(**kwargs)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
