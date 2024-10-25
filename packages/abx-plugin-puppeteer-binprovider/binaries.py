__package__ = 'plugins_pkg.puppeteer'

from typing import List

from pydantic import InstanceOf
from pydantic_pkgr import BinProvider, BinName


from abx.archivebox.base_binary import BaseBinary, env

from plugins_pkg.npm.binproviders import LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER


###################### Config ##########################


class PuppeteerBinary(BaseBinary):
    name: BinName = "puppeteer"

    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_NPM_BINPROVIDER, SYS_NPM_BINPROVIDER, env]


PUPPETEER_BINARY = PuppeteerBinary()
