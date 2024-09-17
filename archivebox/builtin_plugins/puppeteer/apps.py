from typing import List, Optional

from django.conf import settings

# Depends on other PyPI/vendor packages:
from pydantic import InstanceOf, Field
from pydantic_pkgr import BinProvider, BinName

# Depends on other Django apps:
from plugantic.base_plugin import BasePlugin
from plugantic.base_configset import BaseConfigSet, ConfigSectionName
from plugantic.base_binary import BaseBinary, env
# from plugantic.base_extractor import BaseExtractor
# from plugantic.base_queue import BaseQueue
from plugantic.base_hook import BaseHook
from plugantic.ansible_utils import run_playbook

# Depends on Other Plugins:
from builtin_plugins.npm.apps import npm


###################### Config ##########################


class PuppeteerDependencyConfigs(BaseConfigSet):
    section: ConfigSectionName = 'DEPENDENCY_CONFIG'

    PUPPETEER_BINARY: str = Field(default='wget')
    PUPPETEER_ARGS: Optional[List[str]] = Field(default=None)
    PUPPETEER_EXTRA_ARGS: List[str] = []
    PUPPETEER_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']

class PuppeteerConfigs(PuppeteerDependencyConfigs):
    # section: ConfigSectionName = 'ALL_CONFIGS'
    pass

DEFAULT_GLOBAL_CONFIG = {
}

PUPPETEER_CONFIG = PuppeteerConfigs(**DEFAULT_GLOBAL_CONFIG)


INSTALL_BIN = './install_puppeteer.yml'


class ChromeBinary(BaseBinary):
    name: BinName = 'chrome'
    binproviders_supported: List[InstanceOf[BinProvider]] = [npm, env]

    
    def install(self, *args, quiet=False) -> "ChromeBinary":
        
        install_playbook = self.plugin_dir / 'install_puppeteer.yml'
        
        chrome_bin = run_playbook(install_playbook, data_dir=settings.CONFIG.OUTPUT_DIR, quiet=quiet).BINARIES.chrome

        return self.__class__.model_validate(
            {
                **self.model_dump(),
                "loaded_abspath": chrome_bin.symlink,
                "loaded_version": chrome_bin.version,
                "loaded_binprovider": env,
                "binproviders_supported": self.binproviders_supported,
            }
        )
        

CHROME_BINARY = ChromeBinary()

PLUGIN_BINARIES = [CHROME_BINARY]

class PuppeteerPlugin(BasePlugin):
    app_label: str ='puppeteer'
    verbose_name: str = 'SingleFile'

    hooks: List[InstanceOf[BaseHook]] = [
        PUPPETEER_CONFIG,
        CHROME_BINARY,
    ]



PLUGIN = PuppeteerPlugin()
PLUGIN.register(settings)
DJANGO_APP = PLUGIN.AppConfig
