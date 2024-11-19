#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox config'

import sys
import argparse
from pathlib import Path

from typing import Optional, List, IO

from archivebox.misc.util import docstring
from archivebox.config import DATA_DIR
from archivebox.misc.logging_util import SmartFormatter, accept_stdin



# @enforce_types
def config(config_options_str: Optional[str]=None,
           config_options: Optional[List[str]]=None,
           get: bool=False,
           set: bool=False,
           search: bool=False,
           reset: bool=False,
           out_dir: Path=DATA_DIR) -> None:
    """Get and set your ArchiveBox project configuration values"""

    from rich import print

    check_data_folder()
    if config_options and config_options_str:
        stderr(
            '[X] You should either pass config values as an arguments '
            'or via stdin, but not both.\n',
            color='red',
        )
        raise SystemExit(2)
    elif config_options_str:
        config_options = config_options_str.split('\n')

    FLAT_CONFIG = archivebox.pm.hook.get_FLAT_CONFIG()
    CONFIGS = archivebox.pm.hook.get_CONFIGS()
    
    config_options = config_options or []

    no_args = not (get or set or reset or config_options)

    matching_config = {}
    if search:
        if config_options:
            config_options = [get_real_name(key) for key in config_options]
            matching_config = {key: FLAT_CONFIG[key] for key in config_options if key in FLAT_CONFIG}
            for config_section in CONFIGS.values():
                aliases = config_section.aliases
                
                for search_key in config_options:
                    # search all aliases in the section
                    for alias_key, key in aliases.items():
                        if search_key.lower() in alias_key.lower():
                            matching_config[key] = config_section.model_dump()[key]
                    
                    # search all keys and values in the section
                    for existing_key, value in config_section.model_dump().items():
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
                stderr()
                stderr('[X] These options failed to get', color='red')
                stderr('    {}'.format('\n    '.join(config_options)))
                raise SystemExit(1)
        else:
            matching_config = FLAT_CONFIG
        
        print(printable_config(matching_config))
        raise SystemExit(not matching_config)
    elif set:
        new_config = {}
        failed_options = []
        for line in config_options:
            if line.startswith('#') or not line.strip():
                continue
            if '=' not in line:
                stderr('[X] Config KEY=VALUE must have an = sign in it', color='red')
                stderr(f'    {line}')
                raise SystemExit(2)

            raw_key, val = line.split('=', 1)
            raw_key = raw_key.upper().strip()
            key = get_real_name(raw_key)
            if key != raw_key:
                stderr(f'[i] Note: The config option {raw_key} has been renamed to {key}, please use the new name going forwards.', color='lightyellow')

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
                    # import ipdb; ipdb.set_trace()

            if side_effect_changes:
                stderr()
                stderr('[i] Note: This change also affected these other options that depended on it:', color='lightyellow')
                print('    {}'.format(printable_config(side_effect_changes, prefix='    ')))
        if failed_options:
            stderr()
            stderr('[X] These options failed to set (check for typos):', color='red')
            stderr('    {}'.format('\n    '.join(failed_options)))
            raise SystemExit(1)
    elif reset:
        stderr('[X] This command is not implemented yet.', color='red')
        stderr('    Please manually remove the relevant lines from your config file:')
        raise SystemExit(2)
    else:
        stderr('[X] You must pass either --get or --set, or no arguments to get the whole config.', color='red')
        stderr('    archivebox config')
        stderr('    archivebox config --get SOME_KEY')
        stderr('    archivebox config --set SOME_KEY=SOME_VALUE')
        raise SystemExit(2)




@docstring(config.__doc__)
def main(args: Optional[List[str]]=None, stdin: Optional[IO]=None, pwd: Optional[str]=None) -> None:
    parser = argparse.ArgumentParser(
        prog=__command__,
        description=config.__doc__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    parser.add_argument(
        '--search',
        action='store_true',
        help="Search config KEYs, VALUEs, and ALIASES for the given term",
    )
    group.add_argument(
        '--get', #'-g',
        action='store_true',
        help="Get the value for the given config KEYs",
    )
    group.add_argument(
        '--set', #'-s',
        action='store_true',
        help="Set the given KEY=VALUE config values",
    )
    group.add_argument(
        '--reset', #'-s',
        action='store_true',
        help="Reset the given KEY config values to their defaults",
    )
    parser.add_argument(
        'config_options',
        nargs='*',
        type=str,
        help='KEY or KEY=VALUE formatted config values to get or set',
    )
    command = parser.parse_args(args or ())

    config_options_str = ''
    if not command.config_options:
        config_options_str = accept_stdin(stdin)

    config(
        config_options_str=config_options_str,
        config_options=command.config_options,
        search=command.search,
        get=command.get,
        set=command.set,
        reset=command.reset,
        out_dir=Path(pwd) if pwd else DATA_DIR,
    )


if __name__ == '__main__':
    main(args=sys.argv[1:], stdin=sys.stdin)
