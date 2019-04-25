#!/usr/bin/env python3

__package__ = 'archivebox.cli'
__command__ = 'archivebox config'
__description__ = 'Get and set your ArchiveBox project configuration values'

import sys
import argparse

from typing import Optional, List

from ..legacy.util import SmartFormatter
from ..legacy.config import (
    check_data_folder,
    OUTPUT_DIR,
    write_config_file,
    CONFIG,
    ConfigDict,
    stderr,
)


def main(args: List[str]=None, stdin: Optional[str]=None) -> None:
    check_data_folder()
    
    args = sys.argv[1:] if args is None else args

    parser = argparse.ArgumentParser(
        prog=__command__,
        description=__description__,
        add_help=True,
        formatter_class=SmartFormatter,
    )
    group = parser.add_mutually_exclusive_group()
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
    parser.add_argument(
        'config_options',
        nargs='*',
        type=str,
        help='KEY or KEY=VALUE formatted config values to get or set',
    )
    command = parser.parse_args(args)

    if stdin or not sys.stdin.isatty():
        stdin_raw_text = stdin or sys.stdin.read()
        if stdin_raw_text and command.config_options:
            stderr(
                '[X] You should either pass config values as an arguments '
                'or via stdin, but not both.\n',
                color='red',
            )
            raise SystemExit(1)

        config_options = stdin_raw_text.split('\n')
    else:
        config_options = command.config_options

    no_args = not (command.get or command.set or command.config_options)

    matching_config: ConfigDict = {}
    if command.get or no_args:
        if config_options:
            matching_config = {key: CONFIG[key] for key in config_options if key in CONFIG}
            failed_config = [key for key in config_options if key not in CONFIG]
            if failed_config:
                stderr()
                stderr('[X] These options failed to get', color='red')
                stderr('    {}'.format('\n    '.join(config_options)))
                raise SystemExit(1)
        else:
            matching_config = CONFIG
        
        print('\n'.join(f'{key}={val}' for key, val in matching_config.items()))
        raise SystemExit(not matching_config)
    elif command.set:
        new_config = {}
        failed_options = []
        for line in config_options:
            if line.startswith('#') or not line.strip():
                continue
            if '=' not in line:
                stderr('[X] Config KEY=VALUE must have an = sign in it', color='red')
                stderr(f'    {line}')
                raise SystemExit(2)

            key, val = line.split('=')
            if key.upper().strip() in CONFIG:
                new_config[key.upper().strip()] = val.strip()
            else:
                failed_options.append(line)

        if new_config:
            matching_config = write_config_file(new_config, out_dir=OUTPUT_DIR)
            print('\n'.join(f'{key}={val}' for key, val in matching_config.items()))
        if failed_options:
            stderr()
            stderr('[X] These options failed to set:', color='red')
            stderr('    {}'.format('\n    '.join(failed_options)))
        raise SystemExit(bool(failed_options))
    else:
        stderr('[X] You must pass either --get or --set, or no arguments to get the whole config.', color='red')
        stderr('    archivebox config')
        stderr('    archivebox config --get SOME_KEY')
        stderr('    archivebox config --set SOME_KEY=SOME_VALUE')
        raise SystemExit(2)

if __name__ == '__main__':
    main()
