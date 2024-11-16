__package__ = 'abx_plugin_puppeteer'

from typing import List

from pydantic import InstanceOf
from abx_pkg import BinProvider, BinName, Binary


from abx_plugin_default_binproviders import env

from abx_plugin_npm.binproviders import LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER


###################### Config ##########################


class PuppeteerBinary(Binary):
    name: BinName = "puppeteer"

    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]


PUPPETEER_BINARY = PuppeteerBinary()
