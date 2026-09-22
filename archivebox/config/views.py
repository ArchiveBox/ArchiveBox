__package__ = "archivebox.config"

import inspect
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from admin_data_views.typing import ItemContext, SectionData, TableContext
from admin_data_views.utils import ItemLink, render_with_item_view, render_with_table_view
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from archivebox.config import CONSTANTS
from archivebox.machine.models import Binary
from archivebox.misc.util import parse_date

ENVIRONMENT_BINARIES_BASE_URL = "/admin/environment/binaries/"
INSTALLED_BINARIES_BASE_URL = "/admin/machine/binary/"
LOG_DETAIL_TAIL_BYTES = 100_000


def _read_text_tail(path: Path, max_bytes: int = LOG_DETAIL_TAIL_BYTES) -> str:
    with path.open("rb") as log_file:
        size = path.stat().st_size
        log_file.seek(max(size - max_bytes, 0))
        return log_file.read(max_bytes).decode("utf-8", errors="replace")


def is_superuser(request: HttpRequest) -> bool:
    return bool(request.user.is_superuser)


def format_parsed_datetime(value: object) -> str:
    parsed = parse_date(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else ""


def get_environment_binary_url(name: str) -> str:
    return f"{ENVIRONMENT_BINARIES_BASE_URL}{quote(name)}/"


def get_installed_binary_change_url(name: str, binary: Binary | None) -> str | None:
    if binary is None or not binary.id:
        return None

    base_url = binary.admin_change_url
    changelist_filters = urlencode({"q": name})
    return f"{base_url}?{urlencode({'_changelist_filters': changelist_filters})}"


def render_binary_detail_description(name: str, merged: dict[str, Any], db_binary: Any) -> str:
    installed_binary_url = get_installed_binary_change_url(name, db_binary)

    if installed_binary_url:
        return str(
            format_html(
                '<code>{}</code><br/><a href="{}">View Installed Binary Record</a>',
                merged["abspath"],
                installed_binary_url,
            ),
        )

    return str(format_html("<code>{}</code>", merged["abspath"]))


def obj_to_yaml(obj: Any, indent: int = 0) -> str:
    indent_str = "  " * indent
    if indent == 0:
        indent_str = "\n"  # put extra newline between top-level entries

    if isinstance(obj, dict):
        if not obj:
            return "{}"
        result = "\n"
        for key, value in obj.items():
            result += f"{indent_str}{key}:{obj_to_yaml(value, indent + 1)}\n"
        return result

    elif isinstance(obj, list):
        if not obj:
            return "[]"
        result = "\n"
        for item in obj:
            result += f"{indent_str}- {obj_to_yaml(item, indent + 1).lstrip()}\n"
        return result.rstrip()

    elif isinstance(obj, str):
        if "\n" in obj:
            return f" |\n{indent_str}  " + obj.replace("\n", f"\n{indent_str}  ")
        else:
            return f" {obj}"

    elif isinstance(obj, (int, float, bool)):
        return f" {obj!s}"

    elif callable(obj):
        source = (
            "\n".join("" if "def " in line else line for line in inspect.getsource(obj).split("\n") if line.strip())
            .split("lambda: ")[-1]
            .rstrip(",")
        )
        return f" {indent_str}  " + source.replace("\n", f"\n{indent_str}  ")

    else:
        return f" {obj!s}"


def _binary_sort_key(binary: Binary) -> tuple[int, int, int, Any]:
    return (
        int(binary.status == Binary.StatusChoices.INSTALLED),
        int(bool(binary.version)),
        int(bool(binary.abspath)),
        binary.modified_at,
    )


def get_db_binaries_by_name() -> dict[str, Binary]:
    """Group Binary rows by a URL-safe canonical name.

    Hooks occasionally emit ``BinaryEvent.name`` carrying an abspath rather
    than a short binary name (see ``services/binary_service.py``). That used
    to leak ``name='/Users/.../bin/foo'`` rows into the DB, which then broke
    ``/admin/environment/binaries`` because the admin URL regex is
    ``(?P<key>[^/]+)``. Canonicalize at the keying step so duplicates fold
    into the real binary and the admin link key stays slash-free regardless
    of legacy DB state.
    """
    from archivebox.machine.models import _canonical_binary_name

    grouped: dict[str, list[Binary]] = {}
    binary_name_aliases = {
        "youtube-dl": "yt-dlp",
    }
    for binary in Binary.objects.all():
        canonical_name = _canonical_binary_name(binary.name)
        canonical_name = binary_name_aliases.get(canonical_name, canonical_name)
        if not canonical_name:
            continue
        grouped.setdefault(canonical_name, []).append(binary)

    return {name: max(records, key=_binary_sort_key) for name, records in grouped.items()}


@render_with_table_view
def binaries_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    rows = {
        "Binary Name": [],
        "Found Version": [],
        "Provided By": [],
        "Found Abspath": [],
    }

    db_binaries = get_db_binaries_by_name()
    all_binary_names = sorted(db_binaries.keys())

    for name in all_binary_names:
        binary = db_binaries.get(name)
        binary_is_valid = bool(binary and binary.is_valid)

        rows["Binary Name"].append(ItemLink(name, key=name))

        if binary_is_valid:
            rows["Found Version"].append(f"✅ {binary.version}" if binary.version else "✅ found")
            rows["Provided By"].append(binary.binprovider or "-")
            rows["Found Abspath"].append(binary.abspath or "-")
        else:
            rows["Found Version"].append("❌ missing")
            rows["Provided By"].append("-")
            rows["Found Abspath"].append("-")

    return TableContext(
        title="Binaries",
        table=rows,
    )


@render_with_item_view
def binary_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    key = {
        "youtube-dl": "yt-dlp",
    }.get(key, key)
    db_binary = get_db_binaries_by_name().get(key)
    binary_is_valid = bool(db_binary and db_binary.is_valid)
    if binary_is_valid:
        binary_data = db_binary.to_json()
        section: SectionData = {
            "name": key,
            "description": mark_safe(render_binary_detail_description(key, binary_data, db_binary)),
            "fields": {
                "name": key,
                "binprovider": db_binary.binprovider or "-",
                "abspath": db_binary.abspath or "not found",
                "version": db_binary.version or "unknown",
                "sha256": db_binary.sha256,
                "status": db_binary.status,
            },
            "help_texts": {},
        }
        return ItemContext(
            slug=key,
            title=key,
            data=[section],
        )

    section: SectionData = {
        "name": key,
        "description": "No persisted Binary record found",
        "fields": {
            "name": key,
            "binprovider": db_binary.binprovider if db_binary else "not recorded",
            "abspath": db_binary.abspath if db_binary else "not recorded",
            "version": db_binary.version if db_binary else "N/A",
            "status": db_binary.status if db_binary else "unrecorded",
        },
        "help_texts": {},
    }
    return ItemContext(
        slug=key,
        title=key,
        data=[section],
    )


@render_with_table_view
def worker_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    rows = {
        "Name": [],
        "Type": [],
        "State": [],
        "PID": [],
        "Started": [],
        "Command": [],
        "Logfile": [],
        "Exit Status": [],
    }

    from archivebox.workers.supervisord_util import get_existing_supervisord_process

    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        return TableContext(
            title="No running worker processes",
            table=rows,
        )

    all_config: dict[str, dict[str, object]] = {}
    config_items = supervisor.getAllConfigInfo()
    if not isinstance(config_items, list):
        config_items = []
    for config_data in config_items:
        if not isinstance(config_data, dict):
            continue
        config_name = config_data.get("name")
        if not isinstance(config_name, str):
            continue
        all_config[config_name] = config_data

    # Collect every PID we plan to show so we can resolve them to Process rows
    # in a single query. supervisord's per-worker description carries the pid
    # in the form ``pid 12345, uptime 0:01:23`` (or just the bare ``pid``
    # placeholder when stopped); we ignore non-numeric values.
    process_items = supervisor.getAllProcessInfo()
    if not isinstance(process_items, list):
        process_items = []

    def _parse_worker_pid_and_uptime(description: str) -> tuple[int | None, str]:
        body = description.replace("pid ", "", 1)
        pid_part, _, uptime_part = body.partition(", uptime ")
        try:
            return int(pid_part.strip()), uptime_part.strip()
        except ValueError:
            return None, ""

    pids: set[int] = set()
    supervisor_pid = supervisor.getPID()
    if isinstance(supervisor_pid, int):
        pids.add(supervisor_pid)
    for proc_data in process_items:
        if not isinstance(proc_data, dict):
            continue
        pid_int, _ = _parse_worker_pid_and_uptime(str(proc_data.get("description") or ""))
        if pid_int is not None:
            pids.add(pid_int)

    pid_to_process_id: dict[int, str] = {}
    pid_to_process_type: dict[int, str] = {}
    if pids:
        try:
            from archivebox.machine.models import Machine, Process

            for row in (
                Process.objects.filter(machine=Machine.current(), pid__in=pids)
                .order_by("pid", "-started_at", "-created_at")
                .only("id", "pid", "process_type")
            ):
                if row.pid in pid_to_process_id:
                    continue  # keep the most recent row per PID
                pid_to_process_id[row.pid] = str(row.id)
                pid_to_process_type[row.pid] = row.process_type

        except (ImportError, RuntimeError, TypeError, ValueError):
            pass

    def _pid_cell(pid_value: int | None, uptime_str: str = ""):
        if pid_value is None:
            return ""
        pid_text = str(pid_value)
        process_id = pid_to_process_id.get(pid_value)
        if process_id:
            link = format_html('<a href="/admin/machine/process/{}/change/">{}</a>', process_id, pid_text)
        else:
            link = format_html("{}", pid_text)
        if uptime_str:
            return format_html("{}, uptime {}", link, uptime_str)
        return link

    # Add top row for supervisord process manager. supervisord exposes its
    # state + pid over XML-RPC but not its own start time / exit status / uptime,
    # so we read those from the OS process (or fall back to the Process row
    # recorded in _record_supervisord_process). Exit status stays blank while
    # it's RUNNING — supervisord wouldn't be answering RPC if it had exited.
    rows["Name"].append(ItemLink("supervisord", key="supervisord"))
    rows["Type"].append("supervisord")
    supervisor_state = supervisor.getState()
    state_name = str(supervisor_state.get("statename") if isinstance(supervisor_state, dict) else "")
    rows["State"].append(state_name)

    supervisor_started = ""
    supervisor_uptime = ""
    try:
        import time as _time

        import psutil

        ps_proc = psutil.Process(supervisor_pid)
        create_time = ps_proc.create_time()
        supervisor_started = format_parsed_datetime(create_time)
        seconds = max(int(_time.time() - create_time), 0)
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        supervisor_uptime = f"{hours}:{minutes:02d}:{secs:02d}"
    except (ImportError, RuntimeError, TypeError, ValueError):
        try:
            from archivebox.machine.models import Machine, Process

            row = (
                Process.objects.filter(
                    machine=Machine.current(),
                    process_type=Process.TypeChoices.SUPERVISORD,
                    pid=supervisor_pid,
                )
                .order_by("-started_at")
                .first()
            )
            if row and row.started_at:
                supervisor_started = row.started_at.strftime("%Y-%m-%d %H:%M:%S")
                seconds = max(int((timezone.now() - row.started_at).total_seconds()), 0)
                hours, remainder = divmod(seconds, 3600)
                minutes, secs = divmod(remainder, 60)
                supervisor_uptime = f"{hours}:{minutes:02d}:{secs:02d}"
        except (RuntimeError, TypeError, ValueError):
            pass

    rows["PID"].append(_pid_cell(supervisor_pid if isinstance(supervisor_pid, int) else None, supervisor_uptime))
    rows["Started"].append(supervisor_started or "-")

    rows["Command"].append("supervisord --configuration=tmp/supervisord.conf")
    rows["Logfile"].append(
        format_html(
            '<a href="/admin/environment/logs/{}/">{}</a>',
            "supervisord",
            "logs/supervisord.log",
        ),
    )
    rows["Exit Status"].append("" if state_name == "RUNNING" else "-")

    # Add a row for each worker process managed by supervisord
    for proc_data in process_items:
        if not isinstance(proc_data, dict):
            continue
        proc_name = str(proc_data.get("name") or "")
        proc_description = str(proc_data.get("description") or "")
        proc_start = proc_data.get("start")
        proc_logfile = str(proc_data.get("stdout_logfile") or "")
        proc_config = all_config.get(proc_name, {})
        pid_int, uptime_str = _parse_worker_pid_and_uptime(proc_description)

        rows["Name"].append(ItemLink(proc_name, key=proc_name))
        # Prefer the Process row's process_type when we have one (e.g. "worker",
        # "hook"); otherwise fall back to the generic "worker" label since
        # everything in this loop is supervisord-managed.
        rows["Type"].append(pid_to_process_type.get(pid_int, "worker") if pid_int else "worker")
        rows["State"].append(str(proc_data.get("statename") or ""))
        rows["PID"].append(_pid_cell(pid_int, uptime_str))
        rows["Started"].append(format_parsed_datetime(proc_start))
        rows["Command"].append(str(proc_config.get("command") or ""))
        rows["Logfile"].append(
            format_html(
                '<a href="/admin/environment/logs/{}/">{}</a>',
                proc_logfile.split("/")[-1].split(".")[0],
                proc_logfile,
            ),
        )
        rows["Exit Status"].append(str(proc_data.get("exitstatus") or ""))

    return TableContext(
        title="Running worker processes",
        table=rows,
    )


@render_with_item_view
def worker_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    from archivebox.workers.supervisord_util import CONFIG_FILE_NAME, get_existing_supervisord_process, get_sock_file, get_worker

    SOCK_FILE = get_sock_file()
    CONFIG_FILE = SOCK_FILE.parent / CONFIG_FILE_NAME

    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        return ItemContext(
            slug="none",
            title="error: No running supervisord process.",
            data=[],
        )

    all_config: list[dict[str, object]] = []
    config_items = supervisor.getAllConfigInfo()
    if not isinstance(config_items, list):
        config_items = []
    for config_data in config_items:
        if isinstance(config_data, dict):
            all_config.append(config_data)

    if key == "supervisord":
        relevant_config = CONFIG_FILE.read_text()
        supervisor_log = CONSTANTS.LOGS_DIR / "supervisord.log"
        with supervisor_log.open("rb") as log_file:
            startup_logs = log_file.read(LOG_DETAIL_TAIL_BYTES).decode("utf-8", errors="replace")
        relevant_logs = _read_text_tail(supervisor_log)
        startup_lines = [line for line in startup_logs.split("\n") if "RPC interface 'supervisor' initialized" in line]
        start_ts = startup_lines[-1].split(",", 1)[0] if startup_lines else ""
        start_dt = parse_date(start_ts)
        uptime = str(timezone.now() - start_dt).split(".")[0] if start_dt else ""
        supervisor_state = supervisor.getState()

        proc: dict[str, object] = {
            "name": "supervisord",
            "pid": supervisor.getPID(),
            "statename": str(supervisor_state.get("statename") if isinstance(supervisor_state, dict) else ""),
            "start": start_ts,
            "stop": None,
            "exitstatus": "",
            "stdout_logfile": "logs/supervisord.log",
            "description": f"pid 000, uptime {uptime}",
        }
    else:
        worker_data = get_worker(supervisor, key)
        proc = worker_data if isinstance(worker_data, dict) else {}
        relevant_config = next((config for config in all_config if config.get("name") == key), {})
        log_result = supervisor.tailProcessStdoutLog(key, -LOG_DETAIL_TAIL_BYTES, LOG_DETAIL_TAIL_BYTES)
        relevant_logs = str(log_result[0] if isinstance(log_result, tuple) else log_result)

    section: SectionData = {
        "name": key,
        "description": key,
        "fields": {
            "Command": str(proc.get("name") or ""),
            "PID": str(proc.get("pid") or ""),
            "State": str(proc.get("statename") or ""),
            "Started": format_parsed_datetime(proc.get("start")),
            "Stopped": format_parsed_datetime(proc.get("stop")),
            "Exit Status": str(proc.get("exitstatus") or ""),
            "Logfile": str(proc.get("stdout_logfile") or ""),
            "Uptime": str(str(proc.get("description") or "").split("uptime ", 1)[-1]),
            "Config": obj_to_yaml(relevant_config) if isinstance(relevant_config, dict) else str(relevant_config),
            "Recent Logs (last 100 KB)": relevant_logs,
        },
        "help_texts": {"Uptime": "How long the process has been running ([days:]hours:minutes:seconds)"},
    }

    return ItemContext(
        slug=key,
        title=key,
        data=[section],
    )


@render_with_table_view
def log_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    log_files: list[Path] = []
    for logfile in sorted(CONSTANTS.LOGS_DIR.glob("*.log"), key=os.path.getmtime)[::-1]:
        if isinstance(logfile, Path):
            log_files.append(logfile)

    rows = {
        "Name": [],
        "Last Updated": [],
        "Size": [],
        "Most Recent Lines": [],
    }

    # Add a row for each worker process managed by supervisord
    for logfile in log_files:
        st = logfile.stat()
        rows["Name"].append(ItemLink("logs" + str(logfile).rsplit("/logs", 1)[-1], key=logfile.name))
        rows["Last Updated"].append(format_parsed_datetime(st.st_mtime))
        rows["Size"].append(f"{st.st_size // 1000} kb")

        with open(logfile, "rb") as f:
            try:
                f.seek(-1024, os.SEEK_END)
            except OSError:
                f.seek(0)
            last_lines = f.read().decode("utf-8", errors="replace").split("\n")
            non_empty_lines = [line for line in last_lines if line.strip()]
            rows["Most Recent Lines"].append(non_empty_lines[-1] if non_empty_lines else "")

    return TableContext(
        title="Debug Log files",
        table=rows,
    )


@render_with_item_view
def log_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    log_file = next(logfile for logfile in CONSTANTS.LOGS_DIR.glob("*.log") if key in logfile.name)

    log_text = _read_text_tail(log_file)
    log_stat = log_file.stat()

    section: SectionData = {
        "name": key,
        "description": key,
        "fields": {
            "Path": str(log_file),
            "Size": f"{log_stat.st_size // 1000} kb",
            "Last Updated": format_parsed_datetime(log_stat.st_mtime),
            "Tail": "\n".join(log_text.split("\n")[-20:]),
            "Recent Log (last 100 KB)": log_text,
        },
    }

    return ItemContext(
        slug=key,
        title=key,
        data=[section],
    )
