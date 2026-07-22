#!/usr/bin/env python3

__package__ = "archivebox.cli"

import sys
import toml
import rich_click as click
from rich import print
from pathlib import Path

from archivebox.misc.util import docstring, enforce_types
from archivebox.misc.toml_util import CustomTOMLEncoder


def _format_toml(config: dict) -> str:
    return toml.dumps(config, encoder=CustomTOMLEncoder()).strip().replace("\n\n", "\n")


@enforce_types
def config(
    *keys,
    get: bool = False,
    set: bool = False,
    search: bool = False,
    reset: bool = False,
    **kwargs,
) -> None:
    """Get and set your ArchiveBox project configuration values"""

    from archivebox.misc.checks import check_data_folder
    from archivebox.misc.logging_util import printable_config
    from abx_plugins.plugins.base.utils import resolve_alias
    from archivebox.config.collection import write_config_file
    from archivebox.config import CONSTANTS_CONFIG
    from archivebox.config.common import ArchiveBoxConfig, get_config, get_all_configs
    from archivebox.plugins.discovery import discover_plugin_configs

    check_data_folder()

    FLAT_CONFIG = get_config().as_dict()
    runtime_derived_keys = ArchiveBoxConfig.runtime_derived_config_keys()
    readonly_config = {key: val for key, val in CONSTANTS_CONFIG.items() if key.isupper() and isinstance(val, Path)}
    writable_config = {key: val for key, val in FLAT_CONFIG.items() if key not in runtime_derived_keys and key not in readonly_config}
    readable_config = {**writable_config, **readonly_config}
    CONFIGS = get_all_configs()
    plugin_schemas = {
        plugin_name: schema.get("properties", {}) for plugin_name, schema in discover_plugin_configs().items() if isinstance(schema, dict)
    }
    core_config_aliases = {
        alias.upper(): field_name
        for field_name, field in ArchiveBoxConfig.model_fields.items()
        for alias in (field_name, str(field.alias or ""))
        if alias
    }

    config_options: list[str] = list(kwargs.pop("key=value", []) or keys or [f"{key}={val}" for key, val in kwargs.items()])
    no_args = not (get or set or reset or config_options)

    matching_config = {}
    if search:
        if config_options:
            search_terms = [key.strip().lower() for key in config_options]

            for existing_key, value in readable_config.items():
                if any(term in existing_key.lower() or term in str(value).lower() for term in search_terms):
                    matching_config[existing_key] = value

            for alias, key in core_config_aliases.items():
                if key in readable_config and any(term in alias.lower() for term in search_terms):
                    matching_config[key] = readable_config[key]

            for schema in plugin_schemas.values():
                for key, metadata in schema.items():
                    if key in readable_config and any(term in key.lower() or term in str(metadata).lower() for term in search_terms):
                        matching_config[key] = readable_config[key]

        print(printable_config(matching_config))
        raise SystemExit(not matching_config)

    elif get or no_args:
        if config_options:
            config_options = [
                core_config_aliases.get(key.upper().strip()) or resolve_alias(key.upper().strip(), plugin_schemas) for key in config_options
            ]
            matching_config = {key: readable_config[key] for key in config_options if key in readable_config}
            failed_config = [key for key in config_options if key not in readable_config]
            if failed_config:
                print("\n[red][X] These options failed to get[/red]")
                print("    {}".format("\n    ".join(config_options)))
                raise SystemExit(1)
        else:
            matching_config = readable_config

        # Display core config sections
        for config_section in CONFIGS.values():
            section_header = config_section.toml_section_header
            if isinstance(section_header, str) and section_header:
                print(f"[grey53]\\[{section_header}][/grey53]")
            else:
                print("[grey53]\\[CONSTANTS]                                        # (read-only)[/grey53]")

            kv_in_section = {key: val for key, val in dict(config_section).items() if key in matching_config}
            print(_format_toml(kv_in_section))
            print("[grey53]################################################################[/grey53]")

        readonly_keys = {key: val for key, val in readonly_config.items() if key in matching_config}
        if readonly_keys:
            print("[grey53]\\[CONSTANTS]                                        # (read-only)[/grey53]")
            print(_format_toml(readonly_keys))
            print("[grey53]################################################################[/grey53]")

        plugin_keys = {}

        # Collect all plugin config keys
        for schema in plugin_schemas.values():
            for key in schema.keys():
                if key in matching_config and key in writable_config:
                    plugin_keys[key] = matching_config[key]

        # Display all plugin config in single [PLUGINS] section
        if plugin_keys:
            print("[grey53]\\[PLUGINS][/grey53]")
            print(_format_toml(plugin_keys))
            print("[grey53]################################################################[/grey53]")

        raise SystemExit(not matching_config)

    elif set:
        new_config = {}
        failed_options = []
        for line in config_options:
            if line.startswith("#") or not line.strip():
                continue
            if "=" not in line:
                print("[red][X] Config KEY=VALUE must have an = sign in it[/red]")
                print(f"    {line}")
                raise SystemExit(2)

            raw_key, val = line.split("=", 1)
            raw_key = raw_key.upper().strip()
            key = core_config_aliases.get(raw_key) or resolve_alias(raw_key, plugin_schemas)
            if key != raw_key:
                print(
                    f"[yellow][i] Note: The config option {raw_key} has been renamed to {key}, please use the new name going forwards.[/yellow]",
                )

            if key in writable_config:
                new_config[key] = val.strip()
            else:
                failed_options.append(line)

        if new_config:
            before = FLAT_CONFIG
            matching_config = write_config_file(new_config)
            after = get_config().as_dict()
            print(printable_config(matching_config))

            side_effect_changes = {}
            for key, val in after.items():
                if key in FLAT_CONFIG and (str(before[key]) != str(after[key])) and (key not in matching_config):
                    side_effect_changes[key] = after[key]

            if side_effect_changes:
                print(file=sys.stderr)
                print("[yellow][i] Note: This change also affected these other options that depended on it:[/yellow]", file=sys.stderr)
                print("    {}".format(printable_config(side_effect_changes, prefix="    ")), file=sys.stderr)

        if failed_options:
            print()
            print("[red][X] These options failed to set (check for typos):[/red]")
            print("    {}".format("\n    ".join(failed_options)))
            raise SystemExit(1)

    elif reset:
        print("[red][X] This command is not implemented yet.[/red]")
        print("    Please manually remove the relevant lines from your config file:")
        raise SystemExit(2)

    else:
        print("[red][X] You must pass either --get or --set, or no arguments to get the whole config.[/red]")
        print("    archivebox config")
        print("    archivebox config --get SOME_KEY")
        print("    archivebox config --set SOME_KEY=SOME_VALUE")
        raise SystemExit(2)


@click.command()
@click.option("--search", is_flag=True, help="Search config KEYs, VALUEs, and ALIASES for the given term")
@click.option("--get", is_flag=True, help="Get the value for the given config KEYs")
@click.option("--set", is_flag=True, help="Set the given KEY=VALUE config values")
@click.option("--reset", is_flag=True, help="Reset the given KEY config values to their defaults")
@click.argument("KEY=VALUE", nargs=-1, type=str)
@docstring(config.__doc__)
def main(**kwargs) -> None:
    config(**kwargs)


if __name__ == "__main__":
    main()
