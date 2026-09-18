from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

_psutil: Any | None = None
try:
    import psutil as _psutil_import

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
else:
    _psutil = _psutil_import

if TYPE_CHECKING:
    import psutil
else:
    psutil = cast(Any, _psutil)

MACHINE_RECHECK_INTERVAL = 7 * 24 * 60 * 60
NETWORK_INTERFACE_RECHECK_INTERVAL = 1 * 60 * 60
BINARY_RECHECK_INTERVAL = 1 * 30 * 60
PROCESS_RECHECK_INTERVAL = 60  # Re-validate every 60 seconds
PID_REUSE_WINDOW = timedelta(hours=24)  # Max age for considering a PID match valid
PROCESS_TIMEOUT_GRACE = timedelta(seconds=30)  # Extra margin before force-cleaning timed-out RUNNING rows
START_TIME_TOLERANCE = 5.0  # Seconds tolerance for start time matching
PROCESS_PID_NAMESPACE_KEY = "_ARCHIVEBOX_PID_NAMESPACE"
