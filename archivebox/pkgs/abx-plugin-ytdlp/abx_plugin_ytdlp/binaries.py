__package__ = 'abx_plugin_ytdlp'

import subprocess
from typing import List

from pydantic import InstanceOf
from abx_pkg import BinProvider, BinName, BinaryOverrides, Binary

from abx_plugin_default_binproviders import apt, brew, env
from abx_plugin_pip.binproviders import LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER

from .config import YTDLP_CONFIG


class YtdlpBinary(Binary):
    name: BinName = YTDLP_CONFIG.YTDLP_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, apt, brew, env]

YTDLP_BINARY = YtdlpBinary()


class FfmpegBinary(Binary):
    name: BinName = 'ffmpeg'
    binproviders_supported: List[InstanceOf[BinProvider]] = [apt, brew, env]

    overrides: BinaryOverrides = {
        'env': {
            # 'abspath': lambda: shutil.which('ffmpeg', PATH=env.PATH),
            'version': lambda: subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True).stdout,
        },
        'apt': {
            # 'abspath': lambda: shutil.which('ffmpeg', PATH=apt.PATH),
            'version': lambda: subprocess.run(['apt', 'show', 'ffmpeg'], capture_output=True, text=True).stdout,
        },
        'brew': {
            # 'abspath': lambda: shutil.which('ffmpeg', PATH=brew.PATH),
            'version': lambda: subprocess.run(['brew', 'info', 'ffmpeg', '--quiet'], capture_output=True, text=True).stdout,
        },
    }

FFMPEG_BINARY = FfmpegBinary()
