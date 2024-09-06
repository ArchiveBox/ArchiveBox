__package__ = 'archivebox.plugantic'

import inspect
from typing import Any

from django.http import HttpRequest
from django.conf import settings
from django.utils.html import format_html, mark_safe

from admin_data_views.typing import TableContext, ItemContext
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink


from django.conf import settings

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
        "Binary": [],
        "Found Version": [],
        "From Plugin": [],
        "Provided By": [],
        "Found Abspath": [],
        "Related Configuration": [],
        "Overrides": [],
        # "Description": [],
    }

    relevant_configs = {
        key: val
        for key, val in settings.CONFIG.items()
        if '_BINARY' in key or '_VERSION' in key
    }

    for plugin in settings.PLUGINS.values():
        for binary in plugin.HOOKS_BY_TYPE.BINARY.values():
            try:
                binary = binary.load()
            except Exception as e:
                print(e)

            rows['Binary'].append(ItemLink(binary.name, key=binary.name))
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
                    # or binary.name.lower().replace('-', '').replace('_', '') in str(config_value).lower()
            )))
            # if not binary.provider_overrides:
                # import ipdb; ipdb.set_trace()
            rows['Overrides'].append(str(obj_to_yaml(binary.provider_overrides) or str(binary.provider_overrides))[:200])
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
        for loaded_binary in loaded_plugin.HOOKS_BY_TYPE.BINARY.values():
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
        try:
            plugin = plugin.load_binaries()
        except Exception as e:
            print(e)

        rows['Name'].append(ItemLink(plugin.id, key=plugin.id))
        rows['verbose_name'].append(str(plugin.verbose_name))
        rows['module'].append(str(plugin.plugin_module))
        rows['source_code'].append(str(plugin.plugin_dir))
        rows['hooks'].append(mark_safe(', '.join(
            f'<a href="/admin/environment/hooks/{hook.id}/">{hook.id}</a>'
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
