__package__ = 'archivebox.config'

import os
import shutil
import inspect
from pathlib import Path
from typing import Any, Dict
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from admin_data_views.typing import TableContext, ItemContext, SectionData
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink

from archivebox.config import CONSTANTS
from archivebox.misc.util import parse_date

from archivebox.machine.models import Binary


# Common binaries to check for
KNOWN_BINARIES = [
    'wget', 'curl', 'chromium', 'chrome', 'google-chrome', 'google-chrome-stable',
    'node', 'npm', 'npx', 'yt-dlp', 'ytdlp', 'youtube-dl',
    'git', 'singlefile', 'readability-extractor', 'mercury-parser',
    'python3', 'python', 'bash', 'zsh',
    'ffmpeg', 'ripgrep', 'rg', 'sonic', 'archivebox',
]


def is_superuser(request: HttpRequest) -> bool:
    return bool(getattr(request.user, 'is_superuser', False))


def format_parsed_datetime(value: object) -> str:
    parsed = parse_date(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else ""


def obj_to_yaml(obj: Any, indent: int = 0) -> str:
    indent_str = "  " * indent
    if indent == 0:
        indent_str = '\n'  # put extra newline between top-level entries

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
        return f" {str(obj)}"

    elif callable(obj):
        source = '\n'.join(
            '' if 'def ' in line else line
            for line in inspect.getsource(obj).split('\n')
            if line.strip()
        ).split('lambda: ')[-1].rstrip(',')
        return f" {indent_str}  " + source.replace("\n", f"\n{indent_str}  ")

    else:
        return f" {str(obj)}"


def get_detected_binaries() -> Dict[str, Dict[str, Any]]:
    """Detect available binaries using shutil.which."""
    binaries = {}

    for name in KNOWN_BINARIES:
        path = shutil.which(name)
        if path:
            binaries[name] = {
                'name': name,
                'abspath': path,
                'version': None,  # Could add version detection later
                'is_available': True,
            }

    return binaries


def get_filesystem_plugins() -> Dict[str, Dict[str, Any]]:
    """Discover plugins from filesystem directories."""
    import json
    from archivebox.hooks import BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR

    plugins = {}

    for base_dir, source in [(BUILTIN_PLUGINS_DIR, 'builtin'), (USER_PLUGINS_DIR, 'user')]:
        if not base_dir.exists():
            continue

        for plugin_dir in base_dir.iterdir():
            if plugin_dir.is_dir() and not plugin_dir.name.startswith('_'):
                plugin_id = f'{source}.{plugin_dir.name}'

                # Find hook scripts
                hooks = []
                for ext in ('sh', 'py', 'js'):
                    hooks.extend(plugin_dir.glob(f'on_*__*.{ext}'))

                # Load config.json if it exists
                config_file = plugin_dir / 'config.json'
                config_data = None
                if config_file.exists():
                    try:
                        with open(config_file, 'r') as f:
                            config_data = json.load(f)
                    except (json.JSONDecodeError, IOError):
                        config_data = None

                plugins[plugin_id] = {
                    'id': plugin_id,
                    'name': plugin_dir.name,
                    'path': str(plugin_dir),
                    'source': source,
                    'hooks': [str(h.name) for h in hooks],
                    'config': config_data,
                }

    return plugins


@render_with_table_view
def binaries_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), 'Must be a superuser to view configuration settings.'

    rows = {
        "Binary Name": [],
        "Found Version": [],
        "Provided By": [],
        "Found Abspath": [],
    }

    # Get binaries from database (previously detected/installed)
    db_binaries = {b.name: b for b in Binary.objects.all()}

    # Get currently detectable binaries
    detected = get_detected_binaries()

    # Merge and display
    all_binary_names = sorted(set(list(db_binaries.keys()) + list(detected.keys())))

    for name in all_binary_names:
        db_binary = db_binaries.get(name)
        detected_binary = detected.get(name)

        rows['Binary Name'].append(ItemLink(name, key=name))

        if db_binary:
            rows['Found Version'].append(f'✅ {db_binary.version}' if db_binary.version else '✅ found')
            rows['Provided By'].append(db_binary.binprovider or 'PATH')
            rows['Found Abspath'].append(str(db_binary.abspath or ''))
        elif detected_binary:
            rows['Found Version'].append('✅ found')
            rows['Provided By'].append('PATH')
            rows['Found Abspath'].append(detected_binary['abspath'])
        else:
            rows['Found Version'].append('❌ missing')
            rows['Provided By'].append('-')
            rows['Found Abspath'].append('-')

    return TableContext(
        title="Binaries",
        table=rows,
    )


@render_with_item_view
def binary_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), 'Must be a superuser to view configuration settings.'

    # Try database first
    try:
        binary = Binary.objects.get(name=key)
        section: SectionData = {
            "name": binary.name,
            "description": str(binary.abspath or ''),
            "fields": {
                'name': binary.name,
                'binprovider': binary.binprovider,
                'abspath': str(binary.abspath),
                'version': binary.version,
                'sha256': binary.sha256,
            },
            "help_texts": {},
        }
        return ItemContext(
            slug=key,
            title=key,
            data=[section],
        )
    except Binary.DoesNotExist:
        pass

    # Try to detect from PATH
    path = shutil.which(key)
    if path:
        section: SectionData = {
            "name": key,
            "description": path,
            "fields": {
                'name': key,
                'binprovider': 'PATH',
                'abspath': path,
                'version': 'unknown',
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
        "description": "Binary not found",
        "fields": {
            'name': key,
            'binprovider': 'not installed',
            'abspath': 'not found',
            'version': 'N/A',
        },
        "help_texts": {},
    }
    return ItemContext(
        slug=key,
        title=key,
        data=[section],
    )


@render_with_table_view
def plugins_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), 'Must be a superuser to view configuration settings.'

    rows = {
        "Name": [],
        "Source": [],
        "Path": [],
        "Hooks": [],
        "Config": [],
    }

    plugins = get_filesystem_plugins()

    for plugin_id, plugin in plugins.items():
        rows['Name'].append(ItemLink(plugin['name'], key=plugin_id))
        rows['Source'].append(plugin['source'])
        rows['Path'].append(format_html('<code>{}</code>', plugin['path']))
        rows['Hooks'].append(', '.join(plugin['hooks']) or '(none)')

        # Show config status
        if plugin.get('config'):
            config_properties = plugin['config'].get('properties', {})
            config_count = len(config_properties)
            rows['Config'].append(f'✅ {config_count} properties' if config_count > 0 else '✅ present')
        else:
            rows['Config'].append('❌ none')

    if not plugins:
        # Show a helpful message when no plugins found
        rows['Name'].append('(no plugins found)')
        rows['Source'].append('-')
        rows['Path'].append(mark_safe('<code>abx_plugins/plugins/</code> or <code>data/custom_plugins/</code>'))
        rows['Hooks'].append('-')
        rows['Config'].append('-')

    return TableContext(
        title="Installed plugins",
        table=rows,
    )


@render_with_item_view
def plugin_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    import json

    assert is_superuser(request), 'Must be a superuser to view configuration settings.'

    plugins = get_filesystem_plugins()

    plugin = plugins.get(key)
    if not plugin:
        return ItemContext(
            slug=key,
            title=f'Plugin not found: {key}',
            data=[],
        )

    # Base fields that all plugins have
    fields = {
        "id": plugin['id'],
        "name": plugin['name'],
        "source": plugin['source'],
        "path": plugin['path'],
        "hooks": ', '.join(plugin['hooks']),
    }

    # Add config.json data if available
    if plugin.get('config'):
        config_json = json.dumps(plugin['config'], indent=2)
        fields["config.json"] = mark_safe(
            '<pre style="max-height: 600px; overflow-y: auto; background: #f5f5f5; '
            f'padding: 10px; border-radius: 4px;"><code>{config_json}</code></pre>'
        )

        # Also extract and display individual config properties for easier viewing
        if 'properties' in plugin['config']:
            config_properties = plugin['config']['properties']
            properties_summary = []
            for prop_name, prop_info in config_properties.items():
                prop_type = prop_info.get('type', 'unknown')
                prop_desc = prop_info.get('description', '')
                properties_summary.append(f"• {prop_name} ({prop_type}): {prop_desc}")

            if properties_summary:
                fields["Config Properties"] = mark_safe('<br/>'.join(properties_summary))

    section: SectionData = {
        "name": plugin['name'],
        "description": plugin['path'],
        "fields": fields,
        "help_texts": {},
    }

    return ItemContext(
        slug=key,
        title=plugin['name'],
        data=[section],
    )


@render_with_table_view
def worker_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    rows = {
        "Name": [],
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

    # Add top row for supervisord process manager
    rows["Name"].append(ItemLink('supervisord', key='supervisord'))
    supervisor_state = supervisor.getState()
    rows["State"].append(str(supervisor_state.get('statename') if isinstance(supervisor_state, dict) else ''))
    rows['PID'].append(str(supervisor.getPID()))
    rows["Started"].append('-')
    rows["Command"].append('supervisord --configuration=tmp/supervisord.conf')
    rows["Logfile"].append(
        format_html(
            '<a href="/admin/environment/logs/{}/">{}</a>',
            'supervisord',
            'logs/supervisord.log',
        )
    )
    rows['Exit Status'].append('0')

    # Add a row for each worker process managed by supervisord
    process_items = supervisor.getAllProcessInfo()
    if not isinstance(process_items, list):
        process_items = []
    for proc_data in process_items:
        if not isinstance(proc_data, dict):
            continue
        proc_name = str(proc_data.get("name") or "")
        proc_description = str(proc_data.get("description") or "")
        proc_start = proc_data.get("start")
        proc_logfile = str(proc_data.get("stdout_logfile") or "")
        proc_config = all_config.get(proc_name, {})

        rows["Name"].append(ItemLink(proc_name, key=proc_name))
        rows["State"].append(str(proc_data.get("statename") or ""))
        rows['PID'].append(proc_description.replace('pid ', ''))
        rows["Started"].append(format_parsed_datetime(proc_start))
        rows["Command"].append(str(proc_config.get("command") or ""))
        rows["Logfile"].append(
            format_html(
                '<a href="/admin/environment/logs/{}/">{}</a>',
                proc_logfile.split("/")[-1].split('.')[0],
                proc_logfile,
            )
        )
        rows["Exit Status"].append(str(proc_data.get("exitstatus") or ""))

    return TableContext(
        title="Running worker processes",
        table=rows,
    )


@render_with_item_view
def worker_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker, get_sock_file, CONFIG_FILE_NAME

    SOCK_FILE = get_sock_file()
    CONFIG_FILE = SOCK_FILE.parent / CONFIG_FILE_NAME

    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        return ItemContext(
            slug='none',
            title='error: No running supervisord process.',
            data=[],
        )

    all_config: list[dict[str, object]] = []
    config_items = supervisor.getAllConfigInfo()
    if not isinstance(config_items, list):
        config_items = []
    for config_data in config_items:
        if isinstance(config_data, dict):
            all_config.append(config_data)

    if key == 'supervisord':
        relevant_config = CONFIG_FILE.read_text()
        relevant_logs = str(supervisor.readLog(0, 10_000_000))
        start_ts = [line for line in relevant_logs.split("\n") if "RPC interface 'supervisor' initialized" in line][-1].split(",", 1)[0]
        start_dt = parse_date(start_ts)
        uptime = str(timezone.now() - start_dt).split(".")[0] if start_dt else ""
        supervisor_state = supervisor.getState()

        proc: Dict[str, object] = {
            "name": "supervisord",
            "pid": supervisor.getPID(),
            "statename": str(supervisor_state.get("statename") if isinstance(supervisor_state, dict) else ""),
            "start": start_ts,
            "stop": None,
            "exitstatus": "",
            "stdout_logfile": "logs/supervisord.log",
            "description": f'pid 000, uptime {uptime}',
        }
    else:
        worker_data = get_worker(supervisor, key)
        proc = worker_data if isinstance(worker_data, dict) else {}
        relevant_config = next((config for config in all_config if config.get('name') == key), {})
        log_result = supervisor.tailProcessStdoutLog(key, 0, 10_000_000)
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
            "Logs": relevant_logs,
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
        rows["Size"].append(f'{st.st_size//1000} kb')

        with open(logfile, 'rb') as f:
            try:
                f.seek(-1024, os.SEEK_END)
            except OSError:
                f.seek(0)
            last_lines = f.read().decode('utf-8', errors='replace').split("\n")
            non_empty_lines = [line for line in last_lines if line.strip()]
            rows["Most Recent Lines"].append(non_empty_lines[-1])

    return TableContext(
        title="Debug Log files",
        table=rows,
    )


@render_with_item_view
def log_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    log_file = [logfile for logfile in CONSTANTS.LOGS_DIR.glob('*.log') if key in logfile.name][0]

    log_text = log_file.read_text()
    log_stat = log_file.stat()

    section: SectionData = {
        "name": key,
        "description": key,
        "fields": {
            "Path": str(log_file),
            "Size": f"{log_stat.st_size//1000} kb",
            "Last Updated": format_parsed_datetime(log_stat.st_mtime),
            "Tail": "\n".join(log_text[-10_000:].split("\n")[-20:]),
            "Full Log": log_text,
        },
    }

    return ItemContext(
        slug=key,
        title=key,
        data=[section],
    )
