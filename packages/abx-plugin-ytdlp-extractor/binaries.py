__package__ = 'plugins_extractor.ytdlp'

import subprocess
from typing import List

from pydantic import InstanceOf
from pydantic_pkgr import BinProvider, BinName, BinaryOverrides

from abx.archivebox.base_binary import BaseBinary, env, apt, brew

from plugins_pkg.pip.binproviders import LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER

from .config import YTDLP_CONFIG


class YtdlpBinary(BaseBinary):
    name: BinName = YTDLP_CONFIG.YTDLP_BINARY
    binproviders_supported: List[InstanceOf[BinProvider]] = [LIB_PIP_BINPROVIDER, VENV_PIP_BINPROVIDER, SYS_PIP_BINPROVIDER, apt, brew, env]

YTDLP_BINARY = YtdlpBinary()


class FfmpegBinary(BaseBinary):
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
