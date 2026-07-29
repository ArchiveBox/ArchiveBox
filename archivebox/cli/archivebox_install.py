#!/usr/bin/env python3

__package__ = "archivebox.cli"

import os
import re
import shutil
from pathlib import Path

import rich_click as click
from rich import print

from archivebox.misc.util import docstring, enforce_types


def _package_name_candidates(install_arg: object) -> set[str]:
    """Return user-facing package tokens represented by a provider install arg."""
    value = str(install_arg).strip()
    if not value or value.startswith("-"):
        return set()

    candidates = {value}
    package_name = re.split(r"==|>=|<=|~=|!=|>|<|\[", value, maxsplit=1)[0]
    if "@" in package_name and not package_name.startswith("@"):
        package_name = package_name.split("@", 1)[0]
    if package_name:
        candidates.add(package_name)
        candidates.add(Path(package_name).name)
    return candidates


def _binary_record_candidates(binary_record: dict) -> set[str]:
    """Return install-name tokens represented by an abx-dl binary request record."""
    name = str(binary_record.get("name") or "")
    display_name = Path(name).expanduser().name if ("/" in name or name.startswith("~")) else name
    candidates = {name, display_name}
    overrides = binary_record.get("overrides") or {}
    if isinstance(overrides, dict):
        for provider_overrides in overrides.values():
            if not isinstance(provider_overrides, dict):
                continue
            install_args = provider_overrides.get("install_args") or ()
            if isinstance(install_args, str):
                install_args = (install_args,)
            for install_arg in install_args:
                candidates.update(_package_name_candidates(install_arg))
    return {candidate for candidate in candidates if candidate}


def _resolve_install_plugin_names(
    requested_names: tuple[str, ...],
) -> list[str]:
    """Resolve `archivebox install <name>` tokens to installable plugin names."""
    from archivebox.config import CONSTANTS
    from archivebox.config.common import get_config, normalize_runtime_config
    from archivebox.machine.models import Machine
    from abx_dl.config import get_required_binary_requests
    from abx_dl.models import discover_plugins, filter_plugins

    plugins = discover_plugins(runtime="archivebox")
    config = get_config(include_machine=False)
    runtime_config = normalize_runtime_config(config.for_crawl(), json_safe=False)
    derived_config = normalize_runtime_config(Machine.current().config, json_safe=False)
    selected_plugins = dict(filter_plugins(plugins, list(requested_names), include_providers=True))
    unmatched_names: list[str] = []

    for requested_name in requested_names:
        if requested_name in selected_plugins:
            continue

        matched_plugin_names: list[str] = []
        for plugin_name, plugin in plugins.items():
            logical_records = get_required_binary_requests(
                plugin,
                plugin.config.required_binaries,
                overrides=runtime_config,
                derived_overrides=derived_config,
                run_output_dir=CONSTANTS.DATA_DIR,
            )
            actual_records = get_required_binary_requests(
                plugin,
                plugin.config.required_binaries,
                overrides=runtime_config,
                derived_overrides=derived_config,
                run_output_dir=CONSTANTS.DATA_DIR,
                logical_names=False,
            )
            for logical_record, actual_record in zip(logical_records, actual_records, strict=False):
                if requested_name in _binary_record_candidates(logical_record) | _binary_record_candidates(actual_record):
                    matched_plugin_names.append(plugin_name)
                    break

        if matched_plugin_names:
            selected_plugins.update(filter_plugins(plugins, matched_plugin_names, include_providers=True))
        else:
            unmatched_names.append(requested_name)

    if unmatched_names:
        raise click.UsageError(f"No plugins or required binaries found matching: {', '.join(unmatched_names)}")

    return sorted(selected_plugins)


def ensure_data_dir_lib_symlink(data_dir: Path, abxpkg_lib_dir: Path) -> Path | None:
    """Expose the shared abxpkg lib dir at DATA_DIR/lib after install."""
    link_path = data_dir / "lib"
    target_config_path = abxpkg_lib_dir.expanduser().absolute()
    target_path = abxpkg_lib_dir.expanduser().resolve()
    from archivebox.config.paths import get_machine_type

    scoped_data_lib_path = (link_path / get_machine_type()).absolute()

    if target_config_path == scoped_data_lib_path:
        if link_path.is_symlink() or link_path.is_file():
            link_path.unlink()
        target_config_path.mkdir(parents=True, exist_ok=True)
        return None

    if link_path.resolve(strict=False) == target_path:
        return None

    target_path.mkdir(parents=True, exist_ok=True)

    if link_path.is_symlink():
        if link_path.resolve(strict=False) == target_path:
            return link_path
        link_path.unlink()
    elif link_path.exists():
        shutil.rmtree(link_path)

    relative_target = os.path.relpath(target_path, start=link_path.parent)
    link_path.symlink_to(relative_target, target_is_directory=True)
    return link_path


@enforce_types
def install(binaries: tuple[str, ...] = (), binproviders: str = "*", dry_run: bool = False) -> None:
    """Detect and install ArchiveBox dependencies by running the abx-dl install flow

    Examples:
        archivebox install                              # Install all dependencies
        archivebox install wget curl                    # Install only wget and curl
        archivebox install --binproviders=pip yt-dlp    # Install yt-dlp using only pip
        archivebox install --binproviders=brew,apt      # Install all deps using only brew or apt
    """

    from archivebox.config.permissions import IS_ROOT, ARCHIVEBOX_USER, ARCHIVEBOX_GROUP
    from archivebox.config import CONSTANTS
    from archivebox.misc.logging import stderr
    from archivebox.cli.archivebox_init import init

    archive_dir = CONSTANTS.ARCHIVE_DIR

    if dry_run:
        print("[dim]Dry run - would detect ArchiveBox dependencies and run the abx-dl install flow[/dim]")
        return

    if not (os.access(archive_dir, os.R_OK) and archive_dir.is_dir()):
        init()  # must init full index because we need a db to store Binary entries in

    # Show what we're installing
    if binaries:
        print(f"\n[green][+] Installing specific binaries: {', '.join(binaries)}[/green]")
    else:
        print("\n[green][+] Detecting and installing all ArchiveBox dependencies...[/green]")

    if binproviders != "*":
        print(f"[green][+] Using providers: {binproviders}[/green]")

    if IS_ROOT:
        EUID = os.geteuid()
        print()
        print(f"[yellow]:warning:  Running as UID=[blue]{EUID}[/blue].[/yellow]")
        print(f"    DATA_DIR will be owned by [blue]{ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/blue].")
        print()

    # Set up Django
    from archivebox.config.django import setup_django

    setup_django()

    plugin_names = _resolve_install_plugin_names(binaries) if binaries else []
    if binproviders != "*":
        plugin_names.extend(provider.strip() for provider in binproviders.split(",") if provider.strip())

    print("[+] Running installer via abx-dl bus...")
    print()

    from archivebox.services.runner import run_install

    run_install(plugin_names=plugin_names or None)

    from archivebox.config.common import get_config

    config = get_config(include_machine=False)
    ensure_data_dir_lib_symlink(CONSTANTS.DATA_DIR, config.ABXPKG_LIB_DIR)

    print()

    # Check for superuser
    from django.contrib.auth import get_user_model

    User = get_user_model()

    if not User.objects.filter(is_superuser=True).exclude(username="system").exists():
        stderr("\n[+] Don't forget to create a new admin user for the Web UI...", color="green")
        stderr("    archivebox manage createsuperuser")

    print()

    # Show version to display full status including installed binaries
    # Django is already loaded, so just import and call the function directly
    from archivebox.cli.archivebox_version import version as show_version

    show_version(quiet=False, binaries=binaries)


@click.command()
@click.argument("binaries", nargs=-1, type=str, required=False)
@click.option(
    "--binproviders",
    "-p",
    default="*",
    help="Comma-separated list of providers to use (pip,npm,brew,apt,env,custom) or * for all",
    show_default=True,
)
@click.option("--dry-run", "-d", is_flag=True, help="Show what would happen without actually running", default=False)
@docstring(install.__doc__)
def main(**kwargs) -> None:
    install(**kwargs)


if __name__ == "__main__":
    main()
