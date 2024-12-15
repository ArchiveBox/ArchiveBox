
import abx

from typing import Dict

from abx_pkg import (
    AptProvider,
    BrewProvider,
    EnvProvider,
    BinProvider,
)
apt = APT_BINPROVIDER = AptProvider()
brew = BREW_BINPROVIDER = BrewProvider()
env = ENV_BINPROVIDER = EnvProvider()
apt.setup()
brew.setup()
env.setup()


@abx.hookimpl(tryfirst=True)
def get_BINPROVIDERS() -> Dict[str, BinProvider]:
    return {
        'apt': APT_BINPROVIDER,
        'brew': BREW_BINPROVIDER,
        'env': ENV_BINPROVIDER,
    }
