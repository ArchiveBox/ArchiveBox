__package__ = 'pip'

from typing import List, Optional
from pydantic import Field

from abx_spec_config.base_configset import BaseConfigSet


class PipDependencyConfigs(BaseConfigSet):
    USE_PIP: bool = True
    PIP_BINARY: str = Field(default='pip')
    PIP_ARGS: Optional[List[str]] = Field(default=None)
    PIP_EXTRA_ARGS: List[str] = []
    PIP_DEFAULT_ARGS: List[str] = []
    
PIP_CONFIG = PipDependencyConfigs()
