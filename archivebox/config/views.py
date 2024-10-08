__package__ = 'abx.archivebox'

import os
import inspect
from typing import Any, List, Dict, cast
from benedict import benedict

from django.http import HttpRequest
from django.conf import settings
from django.utils import timezone
from django.utils.html import format_html, mark_safe

from admin_data_views.typing import TableContext, ItemContext
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink

from archivebox.config import CONSTANTS
from archivebox.misc.util import parse_date

from machine.models import InstalledBinary


def obj_to_yaml(obj: Any, indent: int=0) -> str:
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

@render_with_table_view
def binaries_list_view(request: HttpRequest, **kwargs) -> TableContext:

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    rows = {
        "Binary Name": [],
        "Found Version": [],
        "From Plugin": [],
        "Provided By": [],
        "Found Abspath": [],
        "Related Configuration": [],
        # "Overrides": [],
        # "Description": [],
    }

    relevant_configs = {
        key: val
        for key, val in settings.FLAT_CONFIG.items()
        if '_BINARY' in key or '_VERSION' in key
    }

    for plugin in settings.PLUGINS.values():
        for binary in plugin.HOOKS_BY_TYPE.get('BINARY', {}).values():
            try:
                installed_binary = InstalledBinary.objects.get_from_db_or_cache(binary)
                binary = installed_binary.load_from_db()
            except Exception as e:
                print(e)

            rows['Binary Name'].append(ItemLink(binary.name, key=binary.name))
            rows['Found Version'].append(f'✅ {binary.loaded_version}' if binary.loaded_version else '❌ missing')
            rows['From Plugin'].append(plugin.plugin_module)
            rows['Provided By'].append(
                ', '.join(
                    f'[{binprovider.name}]' if binprovider.name == getattr(binary.loaded_binprovider, 'name', None) else binprovider.name
                    for binprovider in binary.binproviders_supported
                    if binprovider
                )
                # binary.loaded_binprovider.name
                # if binary.loaded_binprovider else
                # ', '.join(getattr(provider, 'name', str(provider)) for provider in binary.binproviders_supported)
            )
            rows['Found Abspath'].append(str(binary.loaded_abspath or '❌ missing'))
            rows['Related Configuration'].append(mark_safe(', '.join(
                f'<a href="/admin/environment/config/{config_key}/">{config_key}</a>'
                for config_key, config_value in relevant_configs.items()
                    if str(binary.name).lower().replace('-', '').replace('_', '').replace('ytdlp', 'youtubedl') in config_key.lower()
                    or config_value.lower().endswith(binary.name.lower())
                    # or binary.name.lower().replace('-', '').replace('_', '') in str(config_value).lower()
            )))
            # if not binary.provider_overrides:
                # import ipdb; ipdb.set_trace()
            # rows['Overrides'].append(str(obj_to_yaml(binary.provider_overrides) or str(binary.provider_overrides))[:200])
            # rows['Description'].append(binary.description)

    return TableContext(
        title="Binaries",
        table=rows,
    )

@render_with_item_view
def binary_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    binary = None
    plugin = None
    for loaded_plugin in settings.PLUGINS.values():
        for loaded_binary in loaded_plugin.HOOKS_BY_TYPE.get('BINARY', {}).values():
            if loaded_binary.name == key:
                binary = loaded_binary
                plugin = loaded_plugin

    assert plugin and binary, f'Could not find a binary matching the specified name: {key}'

    try:
        binary = binary.load()
    except Exception as e:
        print(e)

    return ItemContext(
        slug=key,
        title=key,
        data=[
            {
                "name": binary.name,
                "description": binary.abspath,
                "fields": {
                    'plugin': plugin.name,
                    'binprovider': binary.loaded_binprovider,
                    'abspath': binary.loaded_abspath,
                    'version': binary.loaded_version,
                    'overrides': obj_to_yaml(binary.provider_overrides),
                    'providers': obj_to_yaml(binary.binproviders_supported),
                },
                "help_texts": {
                    # TODO
                },
            },
        ],
    )


@render_with_table_view
def plugins_list_view(request: HttpRequest, **kwargs) -> TableContext:

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    rows = {
        "Name": [],
        "verbose_name": [],
        "module": [],
        "source_code": [],
        "hooks": [],
    }


    for plugin in settings.PLUGINS.values():
        # try:
        #     plugin.load_binaries()
        # except Exception as e:
        #     print(e)

        rows['Name'].append(ItemLink(plugin.id, key=plugin.id))
        rows['verbose_name'].append(mark_safe(f'<a href="{plugin.docs_url}" target="_blank">{plugin.verbose_name}</a>'))
        rows['module'].append(str(plugin.plugin_module))
        rows['source_code'].append(str(plugin.plugin_dir))
        rows['hooks'].append(mark_safe(', '.join(
            f'<a href="{hook.admin_url}">{hook.id}</a>'
            for hook in plugin.hooks
        )))

    return TableContext(
        title="Installed plugins",
        table=rows,
    )

@render_with_item_view
def plugin_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    plugin = None
    for loaded_plugin in settings.PLUGINS.values():
        if loaded_plugin.id == key:
            plugin = loaded_plugin

    assert plugin, f'Could not find a plugin matching the specified name: {key}'

    try:
        plugin = plugin.load_binaries()
    except Exception as e:
        print(e)

    return ItemContext(
        slug=key,
        title=key,
        data=[
            {
                "name": plugin.id,
                "description": plugin.verbose_name,
                "fields": {
                    "hooks": plugin.hooks,
                    "schema": obj_to_yaml(plugin.model_dump(include=("name", "verbose_name", "app_label", "hooks"))),
                },
                "help_texts": {
                    # TODO
                },
            },
        ],
    )


@render_with_table_view
def worker_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert request.user.is_superuser, "Must be a superuser to view configuration settings."

    rows = {
        "Name": [],
        "State": [],
        "PID": [],
        "Started": [],
        "Command": [],
        "Logfile": [],
        "Exit Status": [],
    }
    
    from queues.supervisor_util import get_existing_supervisord_process
    
    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        return TableContext(
            title="No running worker processes",
            table=rows,
        )
        
    all_config_entries = cast(List[Dict[str, Any]], supervisor.getAllConfigInfo() or [])
    all_config = {config["name"]: benedict(config) for config in all_config_entries}

    # Add top row for supervisord process manager
    rows["Name"].append(ItemLink('supervisord', key='supervisord'))
    rows["State"].append(supervisor.getState()['statename'])
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
    for proc in cast(List[Dict[str, Any]], supervisor.getAllProcessInfo()):
        proc = benedict(proc)
        # {
        #     "name": "daphne",
        #     "group": "daphne",
        #     "start": 1725933056,
        #     "stop": 0,
        #     "now": 1725933438,
        #     "state": 20,
        #     "statename": "RUNNING",
        #     "spawnerr": "",
        #     "exitstatus": 0,
        #     "logfile": "logs/server.log",
        #     "stdout_logfile": "logs/server.log",
        #     "stderr_logfile": "",
        #     "pid": 33283,
        #     "description": "pid 33283, uptime 0:06:22",
        # }
        rows["Name"].append(ItemLink(proc.name, key=proc.name))
        rows["State"].append(proc.statename)
        rows['PID'].append(proc.description.replace('pid ', ''))
        rows["Started"].append(parse_date(proc.start).strftime("%Y-%m-%d %H:%M:%S") if proc.start else '')
        rows["Command"].append(all_config[proc.name].command)
        rows["Logfile"].append(
            format_html(
                '<a href="/admin/environment/logs/{}/">{}</a>',
                proc.stdout_logfile.split("/")[-1].split('.')[0],
                proc.stdout_logfile,
            )
        )
        rows["Exit Status"].append(str(proc.exitstatus))

    return TableContext(
        title="Running worker processes",
        table=rows,
    )


@render_with_item_view
def worker_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert request.user.is_superuser, "Must be a superuser to view configuration settings."

    from queues.supervisor_util import get_existing_supervisord_process, get_worker
    from queues.settings import SUPERVISORD_CONFIG_FILE

    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        return ItemContext(
            slug='none',
            title='error: No running supervisord process.',
            data=[],
        )

    all_config = cast(List[Dict[str, Any]], supervisor.getAllConfigInfo() or [])

    if key == 'supervisord':
        relevant_config = SUPERVISORD_CONFIG_FILE.read_text()
        relevant_logs = cast(str, supervisor.readLog(0, 10_000_000))
        start_ts = [line for line in relevant_logs.split("\n") if "RPC interface 'supervisor' initialized" in line][-1].split(",", 1)[0]
        uptime = str(timezone.now() - parse_date(start_ts)).split(".")[0]

        proc = benedict(
            {
                "name": "supervisord",
                "pid": supervisor.getPID(),
                "statename": supervisor.getState()["statename"],
                "start": start_ts,
                "stop": None,
                "exitstatus": "",
                "stdout_logfile": "logs/supervisord.log",
                "description": f'pid 000, uptime {uptime}',
            }
        )
    else:
        proc = benedict(get_worker(supervisor, key) or {})
        relevant_config = [config for config in all_config if config['name'] == key][0]
        relevant_logs = supervisor.tailProcessStdoutLog(key, 0, 10_000_000)[0]

    return ItemContext(
        slug=key,
        title=key,
        data=[
            {
                "name": key,
                "description": key,
                "fields": {
                    "Command": proc.name,
                    "PID": proc.pid,
                    "State": proc.statename,
                    "Started": parse_date(proc.start).strftime("%Y-%m-%d %H:%M:%S") if proc.start else "",
                    "Stopped": parse_date(proc.stop).strftime("%Y-%m-%d %H:%M:%S") if proc.stop else "",
                    "Exit Status": str(proc.exitstatus),
                    "Logfile": proc.stdout_logfile,
                    "Uptime": (proc.description or "").split("uptime ", 1)[-1],
                    "Config": relevant_config,
                    "Logs": relevant_logs,
                },
                "help_texts": {"Uptime": "How long the process has been running ([days:]hours:minutes:seconds)"},
            },
        ],
    )


@render_with_table_view
def log_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert request.user.is_superuser, "Must be a superuser to view configuration settings."


    log_files = CONSTANTS.LOGS_DIR.glob("*.log")
    log_files = sorted(log_files, key=os.path.getmtime)[::-1]

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
        rows["Last Updated"].append(parse_date(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"))
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
    assert request.user.is_superuser, "Must be a superuser to view configuration settings."

    from django.conf import settings
    
    log_file = [logfile for logfile in CONSTANTS.LOGS_DIR.glob('*.log') if key in logfile.name][0]

    log_text = log_file.read_text()
    log_stat = log_file.stat()

    return ItemContext(
        slug=key,
        title=key,
        data=[
            {
                "name": key,
                "description": key,
                "fields": {
                    "Path": str(log_file),
                    "Size": f"{log_stat.st_size//1000} kb",
                    "Last Updated": parse_date(log_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "Tail": "\n".join(log_text[-10_000:].split("\n")[-20:]),
                    "Full Log": log_text,
                },
            },
        ],
    )
