__package__ = 'archivebox.extractors.wget'

from pathlib import Path

from dynaconf import Dynaconf
from ...config import settings as global_settings

settings = Dynaconf(
    envvar_prefix="ARCHIVEBOX_WGET",
    root_path=Path(__file__).parent,
    settings_file=["settings.toml"]
)

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load this files in the order.

settings.SAVE_WGET = global_settings.SAVE_WGET
settings.SAVE_WARC = global_settings.SAVE_WARC
settings.WGET_VERSION = 123123
settings.TIMEOUT = global_settings.TIMEOUT
settings.WGET_BINARY = global_settings.WGET_BINARY
settings.WGET_ARGS = [
    *global_settings.WGET_ARGS,
    *(["--restrict-file-names={}".format(global_settings.RESTRICT_FILE_NAMES)] if global_settings.RESTRICT_FILE_NAMES else []),
    *(["--page-requisites"] if global_settings.get("SAVE_WGET_REQUISITES") else []),
    *(["--user-agent={}".format(global_settings.WGET_USER_AGENT)] if global_settings.WGET_USER_AGENT else []),
    #["--load-cookies"]
    #["--compression=auto"] if global_settings.WGET_AUTO_COMPRESSION else []
    *([] if settings.SAVE_WARC else ["--timestamping"]),
    *([] if global_settings.CHECK_SSL_VALIDITY else ["--no-check-certificate", "--no-hsts"]),
]