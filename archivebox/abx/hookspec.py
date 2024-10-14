from pathlib import Path

from pluggy import HookimplMarker
from pluggy import HookspecMarker

spec = hookspec = HookspecMarker("abx")
impl = hookimpl = HookimplMarker("abx")


@hookspec
@hookimpl
def get_system_user() -> str:
    return Path('~').expanduser().name

