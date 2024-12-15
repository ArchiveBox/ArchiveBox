__package__ = 'abx_plugin_npm'


from typing import List

from pydantic import InstanceOf
from benedict import benedict

from abx_pkg import BinProvider, Binary, BinName, BinaryOverrides

from abx_plugin_default_binproviders import get_BINPROVIDERS

DEFAULT_BINPROVIDERS = benedict(get_BINPROVIDERS())
env = DEFAULT_BINPROVIDERS.env
apt = DEFAULT_BINPROVIDERS.apt
brew = DEFAULT_BINPROVIDERS.brew


class NodeBinary(Binary):
    name: BinName = 'node'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]
    
    overrides: BinaryOverrides = {
        apt.name: {'packages': ['nodejs']},
    }


NODE_BINARY = NodeBinary()


class NpmBinary(Binary):
    name: BinName = 'npm'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

    overrides: BinaryOverrides = {
        apt.name: {'packages': ['npm']},   # already installed when nodejs is installed
        brew.name: {'install': lambda: None},  # already installed when nodejs is installed
    }
    
NPM_BINARY = NpmBinary()


class NpxBinary(Binary):
    name: BinName = 'npx'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]
    
    overrides: BinaryOverrides = {
        apt.name: {'install': lambda: None},   # already installed when nodejs is installed
        brew.name: {'install': lambda: None},  # already installed when nodejs is installed
    }

NPX_BINARY = NpxBinary()

