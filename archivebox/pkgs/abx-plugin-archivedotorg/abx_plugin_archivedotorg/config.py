from abx_spec_config.base_configset import BaseConfigSet


class ArchivedotorgConfig(BaseConfigSet):
    SAVE_ARCHIVE_DOT_ORG: bool = True


ARCHIVEDOTORG_CONFIG = ArchivedotorgConfig()
