from abx_spec_config import BaseConfigSet


###################### Config ##########################


class NpmDependencyConfigs(BaseConfigSet):
    # USE_NPM: bool = True
    # NPM_BINARY: str = Field(default='npm')
    # NPM_ARGS: Optional[List[str]] = Field(default=None)
    # NPM_EXTRA_ARGS: List[str] = []
    # NPM_DEFAULT_ARGS: List[str] = []
    pass


NPM_CONFIG = NpmDependencyConfigs()

