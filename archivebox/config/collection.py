__package__ = "archivebox.config"

import os

from benedict import benedict

from archivebox.config.constants import CONSTANTS
from archivebox.config.configset import CaseConfigParser


def write_config_file(config: dict[str, str]) -> benedict:
    """load the ini-formatted config file from DATA_DIR/Archivebox.conf"""

    from archivebox.config.common import get_all_configs
    from archivebox.hooks import discover_plugin_configs
    from archivebox.misc.system import atomic_write

    CONFIG_HEADER = """# This is the config file for your ArchiveBox collection.
    #
    # You can add options here manually in INI format, or automatically by running:
    #    archivebox config --set KEY=VALUE
    #
    # If you modify this file manually, make sure to update your archive after by running:
    #    archivebox init
    #
    # A list of all possible config with documentation and examples can be found here:
    #    https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration

    """

    config_path = CONSTANTS.CONFIG_FILE

    if not os.access(config_path, os.F_OK):
        atomic_write(config_path, CONFIG_HEADER)

    config_file = CaseConfigParser()
    config_file.read(config_path)

    with open(config_path, encoding="utf-8") as old:
        atomic_write(f"{config_path}.bak", old.read())

    config_sections = get_all_configs()
    plugin_configs = discover_plugin_configs()

    # Set up sections in empty config file
    for key, val in config.items():
        section_name = None
        for section in config_sections.values():
            if key in type(section).model_fields:
                section_name = section.toml_section_header
                break

        if section_name is None:
            for schema in plugin_configs.values():
                if "properties" in schema and key in schema["properties"]:
                    section_name = "PLUGINS"
                    break

        if section_name is None:
            raise ValueError(f"No config section found for key: {key}")

        if section_name in config_file:
            existing_config = dict(config_file[section_name])
        else:
            existing_config = {}

        config_file[section_name] = benedict({**existing_config, key: val})

    with open(config_path, "w+", encoding="utf-8") as new:
        config_file.write(new)

    updated_config = {}
    try:
        # validate the updated_config by attempting to re-parse it
        from archivebox.config.common import get_config

        updated_config = get_config().as_dict()
    except BaseException:  # lgtm [py/catch-base-exception]
        # something went horribly wrong, revert to the previous version
        with open(f"{config_path}.bak", encoding="utf-8") as old:
            atomic_write(config_path, old.read())

        raise

    if os.access(f"{config_path}.bak", os.F_OK):
        os.remove(f"{config_path}.bak")

    return benedict({key.upper(): updated_config.get(key.upper()) for key in config.keys()})
