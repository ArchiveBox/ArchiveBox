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

    from archivebox.plugins.discovery import get_enabled_plugins, get_plugin_catalog
    from abx_dl.config import get_required_binary_requests
    from abx_dl.dependencies import resolve_binary_requests
    from abx_dl.orchestrator import create_bus
    from abxpkg.binary_service import BinaryEvent, BinaryService

    plugins = get_plugin_catalog()
    enabled_plugin_names = set(get_enabled_plugins(config=config))
    runtime_config = normalize_runtime_config(dict(config.items()), json_safe=False)
    derived_config: dict[str, object] = {}
    if in_data_dir:
        try:
            from archivebox.config.django import setup_django

            setup_django()

            from archivebox.machine.models import Machine

            machine = Machine.current()
            derived_config = normalize_runtime_config(machine.config, json_safe=False)

        except Exception as e:
            prnt()
            prnt("", f"[yellow]Warning: Could not query collection machine config; resolving through abxpkg: {e}[/yellow]")

    declared_binary_specs: dict[str, dict[str, object]] = {}
    for plugin_name, plugin in plugins.items():
        if not plugin_may_have_requested_binary(plugin):
            continue
        plugin_requested = plugin_name.lower() in {name.lower() for name in requested_names}
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
            # This is a diagnostic: recheck the provider instead of trusting an
            # installation record or a cached version, including disabled plugins.
            binary_record["no_cache"] = True
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

    rows_by_binary: dict[str, dict] = {}
    any_rows = False
    any_available = False
    compact_paths = console.is_terminal
    for plugin_name, plugin in plugins.items():
        if not plugin_may_have_requested_binary(plugin):
            continue
        plugin_requested = plugin_name.lower() in {name.lower() for name in requested_names}
        plugin_enabled = plugin_name in enabled_plugin_names
        disabled_by = ", ".join(
            f"{dependency.enabled_key}=False"
            for dependency in plugins.select([plugin_name]).values()
            if not config.get(dependency.enabled_key, True)
        )
        binary_records = get_required_binary_requests(
            plugin,
            plugin.config.required_binaries,
            overrides=runtime_config,
            derived_overrides=derived_config,
            run_output_dir=CONSTANTS.DATA_DIR,
        )
        for binary_record in binary_records:
            binary_record["no_cache"] = True
            actual_name = str(binary_record["name"])
            logical_name = (
                Path(actual_name).expanduser().name
                if ("/" in actual_name or "\\" in actual_name or actual_name.startswith("~"))
                else actual_name
            )
            display_name = logical_name
            if not plugin_requested and not binary_is_requested(logical_name, actual_name, display_name):
                continue

            loaded = loaded_binaries[json.dumps(binary_record, sort_keys=True, default=str)]
            abspath = loaded.abspath if loaded is not None else ""
            version_str = str(loaded.version or "unknown") if loaded is not None else "unknown"
            provider = str(loaded.binprovider or "env") if loaded is not None else "env"
            valid = loaded is not None and Path(abspath).is_file()

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

            if not plugin_enabled:
                rendered_path = f"[grey53]disabled by {disabled_by or 'PLUGINS configuration'}[/grey53]"

            row = {
                "plugin": plugin_name,
                "status": binary_dependency_status(enabled=plugin_enabled, valid=valid),
                "binary": display_name,
                "version": version_str if valid else "-",
                "provider": provider if valid else "-",
                "path": rendered_path,
                "style": "" if plugin_enabled else "dim",
                "enabled": plugin_enabled,
                "valid": valid,
                "plugins": [plugin_name],
                "disabled_by": [disabled_by or "PLUGINS configuration"] if not plugin_enabled else [],
            }
            existing = rows_by_binary.get(display_name)
            if existing is None:
                rows_by_binary[display_name] = row
            else:
                consumers = list(dict.fromkeys([*existing["plugins"], plugin_name]))
                disabled_reasons = list(dict.fromkeys([*existing["disabled_by"], *row["disabled_by"]]))
                # Disabled consumers cannot mask an active requirement. If any
                # active request fails (e.g. a version floor), keep that failure.
                if plugin_enabled and (not existing["enabled"] or not valid):
                    existing.update(row)
                existing["plugins"] = consumers
                existing["disabled_by"] = disabled_reasons
                existing["plugin"] = ", ".join(consumers)
                if not existing["enabled"]:
                    existing["path"] = f"[grey53]disabled by {', '.join(disabled_reasons)}[/grey53]"

    rows = list(rows_by_binary.values())

    if console.is_terminal and console.width < 120:
        from rich.text import Text

        for row in rows:
            heading = Text.from_markup(str(row["status"]))
            heading.append(f" {row['binary']} {row['version']} ({row['provider']}) · {row['plugin']}")
            prnt(heading, style=str(row["style"]))
            path = row["path"]
            prnt(Text.assemble("   ", path if isinstance(path, Text) else Text.from_markup(str(path))), style=str(row["style"]))
    else:
        table = binary_dependency_table(rows)
        table.expand = False
        table.title = None
        table.box = None
        for column in table.columns:
            column.width = None
            column.max_width = None
            column.ratio = None
        prnt(table)

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
