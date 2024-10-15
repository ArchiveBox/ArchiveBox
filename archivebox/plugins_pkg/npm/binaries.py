__package__ = 'plugins_pkg.npm'


from typing import List

from pydantic import InstanceOf

from pydantic_pkgr import BinProvider, BinName, BinaryOverrides


from abx.archivebox.base_binary import BaseBinary, env, apt, brew


class NodeBinary(BaseBinary):
    name: BinName = 'node'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]
    
    overrides: BinaryOverrides = {
        apt.name: {'packages': ['nodejs']},
    }


NODE_BINARY = NodeBinary()


class NpmBinary(BaseBinary):
    name: BinName = 'npm'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

    overrides: BinaryOverrides = {
        apt.name: {'packages': ['npm']},   # already installed when nodejs is installed
        brew.name: {'install': lambda: None},  # already installed when nodejs is installed
    }
    
NPM_BINARY = NpmBinary()


class NpxBinary(BaseBinary):
    name: BinName = 'npx'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]
    
    overrides: BinaryOverrides = {
        apt.name: {'install': lambda: None},   # already installed when nodejs is installed
        brew.name: {'install': lambda: None},  # already installed when nodejs is installed
    }

NPX_BINARY = NpxBinary()

