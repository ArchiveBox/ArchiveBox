"""Machine, interface, binary, and process persistence with process-local caches."""

from __future__ import annotations

from .binaries import Binary as Binary
from .binaries import BinaryManager as BinaryManager
from .binaries import _canonical_binary_name as _canonical_binary_name
from .binaries import _find_existing_binary_for_reference as _find_existing_binary_for_reference
from .constants import (
    BINARY_RECHECK_INTERVAL as BINARY_RECHECK_INTERVAL,
)
from .constants import (
    MACHINE_RECHECK_INTERVAL as MACHINE_RECHECK_INTERVAL,
)
from .constants import (
    NETWORK_INTERFACE_RECHECK_INTERVAL as NETWORK_INTERFACE_RECHECK_INTERVAL,
)
from .constants import (
    PID_REUSE_WINDOW as PID_REUSE_WINDOW,
)
from .constants import (
    PROCESS_PID_NAMESPACE_KEY as PROCESS_PID_NAMESPACE_KEY,
)
from .constants import (
    PROCESS_RECHECK_INTERVAL as PROCESS_RECHECK_INTERVAL,
)
from .constants import (
    PROCESS_TIMEOUT_GRACE as PROCESS_TIMEOUT_GRACE,
)
from .constants import (
    PSUTIL_AVAILABLE as PSUTIL_AVAILABLE,
)
from .constants import (
    START_TIME_TOLERANCE as START_TIME_TOLERANCE,
)
from .interfaces import NetworkInterface as NetworkInterface
from .interfaces import NetworkInterfaceManager as NetworkInterfaceManager
from .machines import Machine as Machine
from .machines import MachineManager as MachineManager
from .machines import _sanitize_machine_config as _sanitize_machine_config
from .processes import Process as Process
from .processes import ProcessManager as ProcessManager
from .processes import _default_exit_code_for_unowned_process as _default_exit_code_for_unowned_process
from .processes import _get_process_binary_env_keys as _get_process_binary_env_keys
from .processes import get_current_pid_namespace as get_current_pid_namespace

_CURRENT_MACHINE: Machine | None = None
_CURRENT_INTERFACE: NetworkInterface | None = None
_CURRENT_BINARIES: dict[str, Binary] = {}
_CURRENT_PROCESS: Process | None = None
