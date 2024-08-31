__package__ = 'archivebox.plugantic'

import inspect
from typing import Any

from django.http import HttpRequest
from django.utils.html import format_html, mark_safe

from admin_data_views.typing import TableContext, ItemContext
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink


from plugantic.plugins import LOADED_PLUGINS
from django.conf import settings

def obj_to_yaml(obj: Any, indent: int=0) -> str:
    indent_str = "  " * indent
    
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

    for plugin in LOADED_PLUGINS:
        for binary in plugin.binaries:
            binary = binary.load_or_install()

            rows['Binary'].append(ItemLink(binary.name, key=binary.name))
            rows['Found Version'].append(binary.loaded_version)
            rows['From Plugin'].append(plugin.name)
            rows['Provided By'].append(binary.loaded_provider)
            rows['Found Abspath'].append(binary.loaded_abspath)
            rows['Related Configuration'].append(mark_safe(', '.join(
                f'<a href="/admin/environment/config/{config_key}/">{config_key}</a>'
                for config_key, config_value in relevant_configs.items()
                    if binary.name.lower().replace('-', '').replace('_', '').replace('ytdlp', 'youtubedl') in config_key.lower()
                    # or binary.name.lower().replace('-', '').replace('_', '') in str(config_value).lower()
            )))
            rows['Overrides'].append(obj_to_yaml(binary.provider_overrides))
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
    for loaded_plugin in LOADED_PLUGINS:
        for loaded_binary in loaded_plugin.binaries:
            if loaded_binary.name == key:
                binary = loaded_binary
                plugin = loaded_plugin

    assert plugin and binary, f'Could not find a binary matching the specified name: {key}'

    binary = binary.load_or_install()

    return ItemContext(
        slug=key,
        title=key,
        data=[
            {
                "name": binary.name,
                "description": binary.description,
                "fields": {
                    'plugin': plugin.name,
                    'binprovider': binary.loaded_provider,
                    'abspath': binary.loaded_abspath,
                    'version': binary.loaded_version,
                    'overrides': obj_to_yaml(binary.provider_overrides),
                    'providers': obj_to_yaml(binary.providers_supported),
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
        "binaries": [],
        "extractors": [],
        "replayers": [],
        "configs": [],
        "description": [],
    }


    for plugin in LOADED_PLUGINS:
        plugin = plugin.load_or_install()

        rows['Name'].append(ItemLink(plugin.name, key=plugin.name))
        rows['binaries'].append(mark_safe(', '.join(
            f'<a href="/admin/environment/binaries/{binary.name}/">{binary.name}</a>'
            for binary in plugin.binaries
        )))
        rows['extractors'].append(', '.join(extractor.name for extractor in plugin.extractors))
        rows['replayers'].append(', '.join(replayer.name for replayer in plugin.replayers))
        rows['configs'].append(mark_safe(', '.join(
            f'<a href="/admin/environment/config/{config_key}/">{config_key}</a>'
            for configset in plugin.configs
                for config_key in configset.__fields__.keys()
                    if config_key != 'section' and config_key in settings.CONFIG
        )))
        rows['description'].append(str(plugin.description))

    return TableContext(
        title="Installed plugins",
        table=rows,
    )

@render_with_item_view
def plugin_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    plugin = None
    for loaded_plugin in LOADED_PLUGINS:
        if loaded_plugin.name == key:
            plugin = loaded_plugin

    assert plugin, f'Could not find a plugin matching the specified name: {key}'

    plugin = plugin.load_or_install()

    return ItemContext(
        slug=key,
        title=key,
        data=[
            {
                "name": plugin.name,
                "description": plugin.description,
                "fields": {
                    'configs': plugin.configs,
                    'binaries': plugin.binaries,
                    'extractors': plugin.extractors,
                    'replayers': plugin.replayers,
                },
                "help_texts": {
                    # TODO
                },
            },
        ],
    )
