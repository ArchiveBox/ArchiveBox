__package__ = 'archivebox.extractors.wget'

from pathlib import Path

from dynaconf import Dynaconf

settings = Dynaconf(
    envvar_prefix="ARCHIVEBOX_WGET",
    root_path=Path(__file__).parent,
    settings_file=["settings.toml"]
)

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load this files in the order.
