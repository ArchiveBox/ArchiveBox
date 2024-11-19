#!/usr/bin/env python3

__package__ = 'archivebox.cli'

import sys
import rich_click as click
from rich import print
from benedict import benedict

from archivebox.misc.util import docstring, enforce_types
from archivebox.misc.toml_util import CustomTOMLEncoder


@enforce_types
def config(*keys,
          get: bool=False,
          set: bool=False, 
          search: bool=False,
          reset: bool=False,
          **kwargs) -> None:
    """Get and set your ArchiveBox project configuration values"""

    import archivebox
    from archivebox.misc.checks import check_data_folder
    from archivebox.misc.logging_util import printable_config
    from archivebox.config.collection import load_all_config, write_config_file, get_real_name

    check_data_folder()

    FLAT_CONFIG = archivebox.pm.hook.get_FLAT_CONFIG()
    CONFIGS = archivebox.pm.hook.get_CONFIGS()
    
    config_options: list[str] = list(kwargs.pop('key=value', []) or keys or [f'{key}={val}' for key, val in kwargs.items()])
    no_args = not (get or set or reset or config_options)

    matching_config = {}
    if search:
        if config_options:
            config_options = [get_real_name(key) for key in config_options]
            matching_config = {key: FLAT_CONFIG[key] for key in config_options if key in FLAT_CONFIG}
            for config_section in CONFIGS.values():
                aliases = getattr(config_section, 'aliases', {})
                
                for search_key in config_options:
                    # search all aliases in the section
                    for alias_key, key in aliases.items():
                        if search_key.lower() in alias_key.lower():
                            matching_config[key] = dict(config_section)[key]
                    
                    # search all keys and values in the section
                    for existing_key, value in dict(config_section).items():
                        if search_key.lower() in existing_key.lower() or search_key.lower() in str(value).lower():
                            matching_config[existing_key] = value
            
        print(printable_config(matching_config))
        raise SystemExit(not matching_config)

    elif get or no_args:
        if config_options:
            config_options = [get_real_name(key) for key in config_options]
            matching_config = {key: FLAT_CONFIG[key] for key in config_options if key in FLAT_CONFIG}
            failed_config = [key for key in config_options if key not in FLAT_CONFIG]
            if failed_config:
                print('\n[red][X] These options failed to get[/red]')
                print('    {}'.format('\n    '.join(config_options)))
                raise SystemExit(1)
        else:
            matching_config = FLAT_CONFIG
        
        for config_section in CONFIGS.values():
            if hasattr(config_section, 'toml_section_header'):
                print(f'[grey53]\\[{config_section.toml_section_header}][/grey53]')
            else:
                print('[grey53]\\[CONSTANTS]                                        # (read-only)[/grey53]')
            
            kv_in_section = {key: val for key, val in dict(config_section).items() if key in matching_config}
            print(benedict(kv_in_section).to_toml(encoder=CustomTOMLEncoder()).strip().replace('\n\n', '\n'))
            print('[grey53]################################################################[/grey53]')
            
        
        raise SystemExit(not matching_config)

    elif set:
        new_config = {}
        failed_options = []
        for line in config_options:
            if line.startswith('#') or not line.strip():
                continue
            if '=' not in line:
                print('[red][X] Config KEY=VALUE must have an = sign in it[/red]')
                print(f'    {line}')
                raise SystemExit(2)

            raw_key, val = line.split('=', 1)
            raw_key = raw_key.upper().strip()
            key = get_real_name(raw_key)
            if key != raw_key:
                print(f'[yellow][i] Note: The config option {raw_key} has been renamed to {key}, please use the new name going forwards.[/yellow]')

            if key in FLAT_CONFIG:
                new_config[key] = val.strip()
            else:
                failed_options.append(line)

        if new_config:
            before = FLAT_CONFIG
            matching_config = write_config_file(new_config)
            after = {**load_all_config(), **archivebox.pm.hook.get_FLAT_CONFIG()}
            print(printable_config(matching_config))

            side_effect_changes = {}
            for key, val in after.items():
                if key in FLAT_CONFIG and (str(before[key]) != str(after[key])) and (key not in matching_config):
                    side_effect_changes[key] = after[key]

            if side_effect_changes:
                print(file=sys.stderr)
                print('[yellow][i] Note: This change also affected these other options that depended on it:[/yellow]', file=sys.stderr)
                print('    {}'.format(printable_config(side_effect_changes, prefix='    ')), file=sys.stderr)

        if failed_options:
            print()
            print('[red][X] These options failed to set (check for typos):[/red]')
            print('    {}'.format('\n    '.join(failed_options)))
            raise SystemExit(1)

    elif reset:
        print('[red][X] This command is not implemented yet.[/red]')
        print('    Please manually remove the relevant lines from your config file:')
        raise SystemExit(2)

    else:
        print('[red][X] You must pass either --get or --set, or no arguments to get the whole config.[/red]')
        print('    archivebox config')
        print('    archivebox config --get SOME_KEY')
        print('    archivebox config --set SOME_KEY=SOME_VALUE')
        raise SystemExit(2)


@click.command()
@click.option('--search', is_flag=True, help='Search config KEYs, VALUEs, and ALIASES for the given term')
@click.option('--get', is_flag=True, help='Get the value for the given config KEYs')
@click.option('--set', is_flag=True, help='Set the given KEY=VALUE config values')
@click.option('--reset', is_flag=True, help='Reset the given KEY config values to their defaults')
@click.argument('KEY=VALUE', nargs=-1, type=str)
@docstring(config.__doc__)
def main(**kwargs) -> None:
    config(**kwargs)


if __name__ == '__main__':
    main()
