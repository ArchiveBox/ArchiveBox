from pathlib import Path

from pluggy import HookimplMarker
from pluggy import HookspecMarker

spec = hookspec = HookspecMarker("abx")
impl = hookimpl = HookimplMarker("abx")


@hookspec
@hookimpl
def get_system_user() -> str:
    # Beware $HOME may not match current EUID, UID, PUID, SUID, there are edge cases
    # - sudo (EUD != UID != SUID)
    # - running with an autodetected UID based on data dir ownership
    #   but mapping of UID:username is broken because it was created
    #   by a different host system, e.g. 911's $HOME outside of docker
    #   might be /usr/lib/lxd instead of /home/archivebox
    # - running as a user that doens't have a home directory
    # - home directory is set to a path that doesn't exist, or is inside a dir we cant read
    return Path('~').expanduser().name

