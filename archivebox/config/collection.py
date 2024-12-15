__package__ = 'archivebox.config'

import os
import json
from typing import Any, Optional, Type, Tuple, Dict

from pathlib import Path
from configparser import ConfigParser

from benedict import benedict

import archivebox

from archivebox.config.constants import CONSTANTS

from archivebox.misc.logging import stderr


def get_real_name(key: str) -> str:
    """get the up-to-date canonical name for a given old alias or current key"""
    CONFIGS = archivebox.pm.hook.get_CONFIGS()
    
    for section in CONFIGS.values():
        try:
            return section.aliases[key]
        except (KeyError, AttributeError):
            pass
    return key


def load_config_val(key: str,
                    default: Any=None,
                    type: Optional[Type]=None,
                    aliases: Optional[Tuple[str, ...]]=None,
                    config: Optional[benedict]=None,
                    env_vars: Optional[os._Environ]=None,
                    config_file_vars: Optional[Dict[str, str]]=None) -> Any:
    """parse bool, int, and str key=value pairs from env"""

    assert isinstance(config, dict)

    is_read_only = type is None
    if is_read_only:
        if callable(default):
            return default(config)
        return default

    # get value from environment variables or config files
    config_keys_to_check = (key, *(aliases or ()))
    val = None
    for key in config_keys_to_check:
        if env_vars:
            val = env_vars.get(key)
            if val:
                break

        if config_file_vars:
            val = config_file_vars.get(key)
            if val:
                break

    is_unset = val is None
    if is_unset:
        if callable(default):
            return default(config)
        return default

    # calculate value based on expected type
    BOOL_TRUEIES = ('true', 'yes', '1')
    BOOL_FALSEIES = ('false', 'no', '0')

    if type is bool:
        if val.lower() in BOOL_TRUEIES:
            return True
        elif val.lower() in BOOL_FALSEIES:
            return False
        else:
            raise ValueError(f'Invalid configuration option {key}={val} (expected a boolean: True/False)')

    elif type is str:
        if val.lower() in (*BOOL_TRUEIES, *BOOL_FALSEIES):
            raise ValueError(f'Invalid configuration option {key}={val} (expected a string, but value looks like a boolean)')
        return val.strip()

    elif type is int:
        if not val.strip().isdigit():
            raise ValueError(f'Invalid configuration option {key}={val} (expected an integer)')
        return int(val.strip())

    elif type is list or type is dict:
        return json.loads(val)
    
    elif type is Path:
        return Path(val)

    raise Exception('Config values can only be str, bool, int, or json')


def load_config_file() -> Optional[benedict]:
    """load the ini-formatted config file from DATA_DIR/Archivebox.conf"""

    config_path = CONSTANTS.CONFIG_FILE
    if os.access(config_path, os.R_OK):
        config_file = ConfigParser()
        config_file.optionxform = str
        config_file.read(config_path)
        # flatten into one namespace
        config_file_vars = benedict({
            key.upper(): val
            for section, options in config_file.items()
                for key, val in options.items()
        })
        # print('[i] Loaded config file', os.path.abspath(config_path))
        # print(config_file_vars)
        return config_file_vars
    return None


def section_for_key(key: str) -> Any:
    for config_section in archivebox.pm.hook.get_CONFIGS().values():
        if hasattr(config_section, key):
            return config_section
    raise ValueError(f'No config section found for key: {key}')


def write_config_file(config: Dict[str, str]) -> benedict:
    """load the ini-formatted config file from DATA_DIR/Archivebox.conf"""

    from archivebox.misc.system import atomic_write

    CONFIG_HEADER = (
    """# This is the config file for your ArchiveBox collection.
    #
    # You can add options here manually in INI format, or automatically by running:
    #    archivebox config --set KEY=VALUE
    #
    # If you modify this file manually, make sure to update your archive after by running:
    #    archivebox init
    #
    # A list of all possible config with documentation and examples can be found here:
    #    https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration

    """)

    config_path = CONSTANTS.CONFIG_FILE

    if not os.access(config_path, os.F_OK):
        atomic_write(config_path, CONFIG_HEADER)

    config_file = ConfigParser()
    config_file.optionxform = str
    config_file.read(config_path)

    with open(config_path, 'r', encoding='utf-8') as old:
        atomic_write(f'{config_path}.bak', old.read())

    # Set up sections in empty config file
    for key, val in config.items():
        section = section_for_key(key)
        assert section is not None
        
        if not hasattr(section, 'toml_section_header'):
            raise ValueError(f'{key} is read-only (defined in {type(section).__module__}.{type(section).__name__}). Refusing to set.')
        
        section_name = section.toml_section_header
        
        if section_name in config_file:
            existing_config = dict(config_file[section_name])
        else:
            existing_config = {}
        
        config_file[section_name] = benedict({**existing_config, key: val})
        section.update_in_place(warn=False, persist=False, **{key: val})

    with open(config_path, 'w+', encoding='utf-8') as new:
        config_file.write(new)

    updated_config = {}
    try:
        # validate the updated_config by attempting to re-parse it
        updated_config = {**load_all_config(), **archivebox.pm.hook.get_FLAT_CONFIG()}
    except BaseException:                                                       # lgtm [py/catch-base-exception]
        # something went horribly wrong, revert to the previous version
        with open(f'{config_path}.bak', 'r', encoding='utf-8') as old:
            atomic_write(config_path, old.read())

        raise

    if os.access(f'{config_path}.bak', os.F_OK):
        os.remove(f'{config_path}.bak')

    return benedict({
        key.upper(): updated_config.get(key.upper())
        for key in config.keys()
    })



def load_config(defaults: Dict[str, Any],
                config: Optional[benedict]=None,
                out_dir: Optional[str]=None,
                env_vars: Optional[os._Environ]=None,
                config_file_vars: Optional[Dict[str, str]]=None) -> benedict:

    env_vars = env_vars or os.environ
    config_file_vars = config_file_vars or load_config_file()

    extended_config = benedict(config.copy() if config else {})
    for key, default in defaults.items():
        try:
            # print('LOADING CONFIG KEY:', key, 'DEFAULT=', default)
            extended_config[key] = load_config_val(
                key,
                default=default['default'],
                type=default.get('type'),
                aliases=default.get('aliases'),
                config=extended_config,
                env_vars=env_vars,
                config_file_vars=config_file_vars,
            )
        except KeyboardInterrupt:
            raise SystemExit(0)
        except Exception as e:
            stderr()
            stderr(f'[X] Error while loading configuration value: {key}', color='red', config=extended_config)
            stderr('    {}: {}'.format(e.__class__.__name__, e))
            stderr()
            stderr('    Check your config for mistakes and try again (your archive data is unaffected).')
            stderr()
            stderr('    For config documentation and examples see:')
            stderr('        https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration')
            stderr()
            # raise
            # raise SystemExit(2)

    return benedict(extended_config)

def load_all_config():
    import abx
    
    flat_config = benedict()
    
    for config_section in abx.pm.hook.get_CONFIGS().values():
        config_section.__init__()
        flat_config.update(dict(config_section))
        
    return flat_config

