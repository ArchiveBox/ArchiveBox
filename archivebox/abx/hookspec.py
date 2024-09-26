from pathlib import Path

from pluggy import HookimplMarker
from pluggy import HookspecMarker

hookspec = HookspecMarker("abx")
hookimpl = HookimplMarker("abx")


@hookspec
def get_system_user() -> str:
    return Path('~').expanduser().name
