#!/usr/bin/env python3

__package__ = "archivebox.cli"

import sys
import os
import json
import asyncio
import platform
import re
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

    candidate_bases: tuple[tuple[Path, str], ...] = (
        (pwd, "./"),
        (lib_dir, "ABXPKG_LIB_DIR/"),
        (personas_dir, "PERSONAS_DIR/"),
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
            if prefix == "ABXPKG_LIB_DIR/":
                return "ABXPKG_LIB_DIR" if not relative_str else f"ABXPKG_LIB_DIR/{relative_str}"
            if prefix == "PERSONAS_DIR/":
                return "PERSONAS_DIR" if not relative_str else f"PERSONAS_DIR/{relative_str}"
            return "~" if not relative_str else f"~/{relative_str}"

    return normalized.as_posix()


def _render_binary_abspath(abspath: str):
    from rich.text import Text

    if abspath.startswith("ABXPKG_LIB_DIR/"):
        return Text.assemble(("ABXPKG_LIB_DIR", "bright_blue"), (abspath.removeprefix("ABXPKG_LIB_DIR"), "green"))
    if abspath == "ABXPKG_LIB_DIR":
        return Text("ABXPKG_LIB_DIR", style="bright_blue")
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


def _binary_record_matches_runtime(installed, lib_dir: Path) -> bool:
    if not installed or not installed.is_valid or not installed.version:
        return False
    try:
        abspath = Path(installed.abspath).expanduser().resolve(strict=False)
        if not abspath.exists():
            return False
        if installed.binprovider not in {"", "env", "apt", "brew"}:
            abspath.relative_to(lib_dir)
    except (OSError, ValueError):
        return False
    return True


def _binary_row_dedupe_key(
    *,
    display_name: str,
    valid: bool,
    version: str,
    provider: str,
    abspath: str,
) -> tuple[str, str, str, str]:
    if not valid:
        return (display_name, "", "", "")
    try:
        resolved_abspath = Path(abspath).expanduser().resolve(strict=False).as_posix()
    except Exception:
        resolved_abspath = abspath
    return (display_name, provider, version, resolved_abspath)


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
    from rich.live import Live
    from abx_dl.tables import binary_dependency_status, binary_dependency_table

    from archivebox.config import CONSTANTS
    from archivebox.config.version import get_COMMIT_HASH, get_BUILD_TIME
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, RUNNING_AS_UID, RUNNING_AS_GID, IN_DOCKER
    from archivebox.config.paths import get_data_locations, get_code_locations
    from archivebox.misc.checks import is_archivebox_source_root
    from archivebox.misc.logging_util import printable_folder_status
    from archivebox.config.common import get_config, normalize_runtime_config

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
        f"IN_QEMU={config.IN_QEMU}",
        f"ARCH={p.machine}",
        f"OS={p.system}",
        f"PLATFORM={platform.platform()}",
        f"PYTHON={sys.implementation.name.title()}" + (" (venv)" if CONSTANTS.IS_INSIDE_VENV else ""),
    )

    try:
        data_locations = get_data_locations(config=config)
        OUTPUT_IS_REMOTE_FS = data_locations.DATA_DIR.is_mount or data_locations.ARCHIVE_DIR.is_mount
    except Exception:
        OUTPUT_IS_REMOTE_FS = False

    try:
        DATA_DIR_STAT = CONSTANTS.DATA_DIR.stat()
        prnt(
            f"EUID={os.geteuid()}:{os.getegid()} UID={RUNNING_AS_UID}:{RUNNING_AS_GID} ARCHIVEBOX_USER={ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}",
            f"FS_UID={DATA_DIR_STAT.st_uid}:{DATA_DIR_STAT.st_gid}",
            f"FS_PERMS={config.OUTPUT_PERMISSIONS}",
            f"FS_ATOMIC={config.ENFORCE_ATOMIC_WRITES}",
            f"FS_REMOTE={OUTPUT_IS_REMOTE_FS}",
        )
    except Exception:
        prnt(
            f"EUID={os.geteuid()}:{os.getegid()} UID={RUNNING_AS_UID}:{RUNNING_AS_GID} ARCHIVEBOX_USER={ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}",
        )

    prnt(
        f"DEBUG={config.DEBUG}",
        f"IS_TTY={config.IS_TTY}",
        f"SUDO={CONSTANTS.IS_ROOT}",
        f"ID={CONSTANTS.MACHINE_ID}:{CONSTANTS.COLLECTION_ID}",
        f"SEARCH_BACKEND={config.SEARCH_BACKEND_ENGINE}",
        f"LDAP={LDAP_ENABLED}",
    )
    prnt()

    in_data_dir = (
        not is_archivebox_source_root(CONSTANTS.DATA_DIR)
        and os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK)
        and os.access(CONSTANTS.CONFIG_FILE, os.R_OK)
    )
    if isinstance(binaries, str):
        requested_names = {name.strip() for name in binaries.split(",") if name.strip()}
    else:
        requested_names = {name for name in (binaries or ()) if name}

    def binary_is_requested(logical_name: str, actual_name: str, display_name: str) -> bool:
        return not requested_names or bool({logical_name, actual_name, display_name} & requested_names)

    def plugin_may_have_requested_binary(plugin) -> bool:
        if not requested_names:
            return True
        aliases = {plugin.name}
        for required_binary in plugin.config.required_binaries:
            raw_name = str(required_binary.name)
            aliases.add(raw_name)
            template_match = re.fullmatch(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", raw_name)
            if template_match:
                config_key = template_match.group(1)
                aliases.add(config_key)
                aliases.add(config_key.removesuffix("_BINARY"))
                default = plugin.config.properties.get(config_key, {}).get("default")
                if default:
                    aliases.add(str(default))
        normalized_aliases = {alias.lower() for alias in aliases}
        return bool({name.lower() for name in requested_names} & normalized_aliases)

    if not in_data_dir:
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

    if not in_data_dir and not requested_names:
        prnt("[pale_green1][i] Binary Dependencies:[/pale_green1]")
        prnt("", "[grey53]Dependency checks require an initialized collection DATA_DIR.[/grey53]")
        prnt()
        prnt("[deep_sky_blue3][i] Code locations:[/deep_sky_blue3]")
        try:
            for name, path in get_code_locations(config=config).items():
                if isinstance(name, str) and isinstance(path, dict):
                    prnt(printable_folder_status(name, path), overflow="ignore", crop=False)
        except Exception as e:
            prnt(f"  [red]Error getting code locations: {e}[/red]")
        prnt()
        prnt("[red][i] Data locations:[/red] (not in a data directory)")
        prnt()
        return []

    prnt("[pale_green1][i] Binary Dependencies:[/pale_green1]")
    failures = []
    seen_failures: set[str] = set()
    seen_rows: set[tuple[str, str, str, str]] = set()

    from archivebox.plugins.discovery import get_enabled_plugins
    from abx_dl.config import get_required_binary_requests
    from abx_dl.dependencies import resolve_binary_requests
    from abx_dl.models import discover_plugins, filter_plugins
    from abx_dl.orchestrator import create_bus
    from abxpkg.binary_service import BinaryEvent, BinaryService

    plugins = discover_plugins(runtime="archivebox")
    enabled_plugins = filter_plugins(plugins, get_enabled_plugins(config=config), include_providers=True)
    enabled_plugin_names = set(enabled_plugins)
    runtime_config = normalize_runtime_config(config.for_crawl(), json_safe=False)
    derived_config: dict[str, object] = {}
    db_binaries = {}
    db_available = False
    if in_data_dir:
        try:
            from archivebox.config.django import setup_django

            setup_django()

            from archivebox.machine.models import Machine, Binary

            machine = Machine.current()
            derived_config = normalize_runtime_config(machine.config, json_safe=False)
            for binary in Binary.objects.filter(machine=machine).order_by("name", "-modified_at"):
                if _binary_record_matches_runtime(binary, config.ABXPKG_LIB_DIR):
                    db_binaries.setdefault(binary.name, binary)
            db_available = True

        except Exception as e:
            prnt()
            prnt("", f"[yellow]Warning: Could not query collection binary records; resolving through abxpkg: {e}[/yellow]")

    declared_binary_specs: dict[str, dict[str, object]] = {}
    for plugin_name, plugin in plugins.items():
        if not plugin_may_have_requested_binary(plugin):
            continue
        plugin_requested = bool(requested_names)
        plugin_enabled = plugin_name in enabled_plugin_names
        binary_records = get_required_binary_requests(
            plugin,
            plugin.config.required_binaries,
            overrides=runtime_config,
            derived_overrides=derived_config,
            run_output_dir=CONSTANTS.DATA_DIR,
        )
        for binary_record in binary_records:
            actual_name = str(binary_record["name"])
            logical_name = (
                Path(actual_name).expanduser().name
                if ("/" in actual_name or "\\" in actual_name or actual_name.startswith("~"))
                else actual_name
            )
            display_name = logical_name
            if not plugin_requested and not binary_is_requested(logical_name, actual_name, display_name):
                continue
            if not plugin_enabled and not requested_names:
                continue
            if _binary_record_matches_runtime(db_binaries.get(logical_name), config.ABXPKG_LIB_DIR):
                continue
            signature = json.dumps(binary_record, sort_keys=True, default=str)
            declared_binary_specs.setdefault(signature, binary_record)

    loaded_binaries: dict[str, BinaryEvent | None] = {}
    if declared_binary_specs:
        binary_bus = create_bus(name="ArchiveBoxVersionBinaryCheck")
        BinaryService(binary_bus, auto_install=False, lib_dir=config.ABXPKG_LIB_DIR)

        async def resolve_declared_binaries() -> dict[str, BinaryEvent | None]:
            try:
                return await resolve_binary_requests(binary_bus, declared_binary_specs)
            finally:
                await binary_bus.wait_until_idle()
                await binary_bus.destroy(clear=False)

        loaded_binaries = asyncio.run(resolve_declared_binaries())

    rows: list[dict[str, object]] = []
    any_rows = False
    any_available = False
    compact_paths = console.is_terminal
    live_enabled = console.is_terminal
    live_cm = Live(binary_dependency_table(rows), console=console, refresh_per_second=8) if live_enabled else None

    def emit_row(row: dict[str, object]) -> None:
        rows.append(row)
        if live_cm is not None:
            live_cm.update(binary_dependency_table(rows), refresh=True)

    if live_cm is not None:
        live_cm.start()
    try:
        for plugin_name, plugin in plugins.items():
            if not plugin_may_have_requested_binary(plugin):
                continue
            plugin_requested = bool(requested_names)
            plugin_enabled = plugin_name in enabled_plugin_names
            binary_records = get_required_binary_requests(
                plugin,
                plugin.config.required_binaries,
                overrides=runtime_config,
                derived_overrides=derived_config,
                run_output_dir=CONSTANTS.DATA_DIR,
            )
            for binary_record in binary_records:
                actual_name = str(binary_record["name"])
                logical_name = (
                    Path(actual_name).expanduser().name
                    if ("/" in actual_name or "\\" in actual_name or actual_name.startswith("~"))
                    else actual_name
                )
                display_name = logical_name
                if not plugin_requested and not binary_is_requested(logical_name, actual_name, display_name):
                    continue

                installed = db_binaries.get(logical_name) if db_available else None
                if _binary_record_matches_runtime(installed, config.ABXPKG_LIB_DIR):
                    abspath = installed.abspath
                    version_str = (installed.version or "unknown")[:15]
                    provider = (installed.binprovider or "env")[:8]
                    valid = True
                elif not plugin_enabled and not requested_names:
                    # `archivebox version` is expected to verify the active runtime, not
                    # cold-load every optional plugin provider. Migration and status
                    # checks often run with PLUGINS narrowed to a tiny set; resolving
                    # disabled plugin binaries there can spend most of the command on
                    # providers the current collection will never execute.
                    continue
                else:
                    loaded = loaded_binaries[json.dumps(binary_record, sort_keys=True, default=str)]
                    abspath = loaded.abspath if loaded is not None else ""
                    version_str = str(loaded.version or "unknown")[:15] if loaded is not None else "unknown"
                    provider = str(loaded.binprovider or "env")[:8] if loaded is not None else "env"
                    valid = loaded is not None

                any_rows = True
                if valid:
                    display_path = (
                        _format_binary_abspath(
                            abspath,
                            pwd=Path.cwd(),
                            lib_dir=config.ABXPKG_LIB_DIR,
                            personas_dir=CONSTANTS.PERSONAS_DIR,
                            home=Path.home(),
                        )
                        if compact_paths
                        else abspath
                    )
                    rendered_path = _render_binary_abspath(display_path) if compact_paths else display_path
                    any_available = True
                else:
                    rendered_path = "[grey53]not installed[/grey53]"
                    if plugin_enabled and display_name not in seen_failures:
                        failures.append(display_name)
                        seen_failures.add(display_name)

                row_key = _binary_row_dedupe_key(
                    display_name=display_name,
                    valid=valid,
                    version=version_str if valid else "-",
                    provider=provider if valid else "-",
                    abspath=abspath,
                )
                if row_key in seen_rows:
                    continue
                seen_rows.add(row_key)

                emit_row(
                    {
                        "plugin": plugin_name,
                        "status": binary_dependency_status(enabled=plugin_enabled, valid=valid),
                        "binary": display_name,
                        "version": version_str if valid else "-",
                        "provider": provider if valid else "-",
                        "path": rendered_path,
                        "style": "" if plugin_enabled else "dim",
                    },
                )

        if db_available:
            for binary_name, installed in db_binaries.items():
                if requested_names and binary_name not in requested_names:
                    continue
                abspath = installed.abspath
                version_str = (installed.version or "unknown")[:15]
                provider = (installed.binprovider or "env")[:8]
                row_key = _binary_row_dedupe_key(
                    display_name=binary_name,
                    valid=True,
                    version=version_str,
                    provider=provider,
                    abspath=abspath,
                )
                if row_key in seen_rows:
                    continue
                seen_rows.add(row_key)

                display_path = (
                    _format_binary_abspath(
                        abspath,
                        pwd=Path.cwd(),
                        lib_dir=config.ABXPKG_LIB_DIR,
                        personas_dir=CONSTANTS.PERSONAS_DIR,
                        home=Path.home(),
                    )
                    if compact_paths
                    else abspath
                )
                emit_row(
                    {
                        "plugin": "(database)",
                        "status": binary_dependency_status(enabled=True, valid=True),
                        "binary": binary_name,
                        "version": version_str,
                        "provider": provider,
                        "path": _render_binary_abspath(display_path) if compact_paths else display_path,
                        "style": "dim",
                    },
                )
                any_rows = True
                any_available = True
    finally:
        if live_cm is not None:
            live_cm.stop()
        else:
            prnt(binary_dependency_table(rows))

    if not any_rows:
        prnt("", "[grey53]No required binaries declared for discovered plugins.[/grey53]")
    elif not any_available:
        prnt("", "[grey53]No binaries detected. Run [green]archivebox install[/green] to detect dependencies.[/grey53]")

    if not binaries:
        # Show code and data locations
        prnt()
        prnt("[deep_sky_blue3][i] Code locations:[/deep_sky_blue3]")
        try:
            for name, path in get_code_locations(config=config).items():
                if isinstance(name, str) and isinstance(path, dict):
                    prnt(printable_folder_status(name, path), overflow="ignore", crop=False)
        except Exception as e:
            prnt(f"  [red]Error getting code locations: {e}[/red]")

        prnt()
        if os.access(CONSTANTS.ARCHIVE_DIR, os.R_OK) or os.access(CONSTANTS.CONFIG_FILE, os.R_OK):
            prnt("[bright_yellow][i] Data locations:[/bright_yellow]")
            try:
                for name, path in get_data_locations(config=config).items():
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
    version(**kwargs)


if __name__ == "__main__":
    main()
