import os
from typing import cast

from admin_data_views.typing import ItemContext, SectionData, TableContext
from admin_data_views.utils import ItemLink, render_with_item_view, render_with_table_view
from django.http import HttpRequest
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from archivebox.config import CONSTANTS, CONSTANTS_CONFIG
from archivebox.config.common import (
    PLUGIN_CONFIG_SCHEMAS,
    SENSITIVE_CONFIG_VALUE_REDACTED,
    _plugin_config_properties,
    find_config_default,
    find_config_section,
    find_config_source,
    find_config_type,
    get_all_configs,
    get_config,
    redact_sensitive_config,
)
from archivebox.config.configset import BaseConfigSet
from archivebox.plugins.views import get_config_definition_link


@render_with_table_view
def live_config_list_view(request: HttpRequest, **kwargs) -> TableContext:
    CONFIGS = get_all_configs()

    assert request.user.is_superuser, "Must be a superuser to view configuration settings."

    merged_config = get_config(redact_sensitive=True)

    rows = {
        "Section": [],
        "Key": [],
        "Type": [],
        "Value": [],
        "Source": [],
        "Default": [],
        # "Documentation": [],
        # "Aliases": [],
    }

    for section_id, section in reversed(list(CONFIGS.items())):
        for key in dict(section):
            rows["Section"].append(section_id)  # section.replace('_', ' ').title().replace(' Config', '')
            rows["Key"].append(ItemLink(key, key=key))
            rows["Type"].append(format_html("<code>{}</code>", find_config_type(key)))

            # Use merged config value (includes machine overrides)
            actual_value = merged_config.get(key, dict(section)[key])
            rows["Value"].append(format_html("<code>{}</code>", actual_value))

            # Show where the value comes from
            source = find_config_source(key, merged_config)
            source_colors = {"Machine": "purple", "Environment": "blue", "File": "green", "Plugin Default": "teal", "Default": "gray"}
            rows["Source"].append(format_html('<code style="color: {}">{}</code>', source_colors.get(source, "gray"), source))

            rows["Default"].append(
                format_html(
                    '<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{}&type=code"><code style="text-decoration: underline">{}</code></a>',
                    key,
                    find_config_default(key) or "See here...",
                ),
            )

    section = "CONSTANT"
    for key in CONSTANTS_CONFIG:
        rows["Section"].append(section)  # section.replace('_', ' ').title().replace(' Config', '')
        rows["Key"].append(ItemLink(key, key=key))
        rows["Type"].append(format_html("<code>{}</code>", type(CONSTANTS_CONFIG[key]).__name__))
        rows["Value"].append(format_html("<code>{}</code>", redact_sensitive_config(CONSTANTS_CONFIG).get(key)))
        rows["Source"].append(mark_safe('<code style="color: gray">Constant</code>'))
        rows["Default"].append(
            format_html(
                '<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{}&type=code"><code style="text-decoration: underline">{}</code></a>',
                key,
                find_config_default(key) or "See here...",
            ),
        )

    return TableContext(
        title="Computed Configuration Values",
        table=rows,
    )


@render_with_item_view
def live_config_value_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    from archivebox.machine.models import Machine

    CONFIGS = get_all_configs()

    assert request.user.is_superuser, "Must be a superuser to view configuration settings."

    merged_config = get_config(redact_sensitive=True)

    # Determine all sources for this config value
    sources_info = []

    # Machine config
    machine = Machine.current()
    machine_admin_url = machine.admin_change_url
    if machine.config and key in machine.config:
        sources_info.append(("Machine", redact_sensitive_config(machine.config).get(key), "purple"))

    # Environment variable
    if key in os.environ:
        sources_info.append(("Environment", redact_sensitive_config(os.environ).get(key), "blue"))

    # Config file value
    if CONSTANTS.CONFIG_FILE.exists():
        file_config = BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE)
        if key in file_config:
            sources_info.append(("File", redact_sensitive_config(file_config).get(key), "green"))

    # Default value
    default_val = find_config_default(key)
    if key in _plugin_config_properties(PLUGIN_CONFIG_SCHEMAS):
        sources_info.append(("Plugin Default", default_val, "gray"))
    elif default_val:
        sources_info.append(("Default", default_val, "gray"))

    # Final computed value
    config_source = find_config_source(key, merged_config)
    final_value = merged_config.get(key, CONFIGS.get(key, None))
    is_redacted = final_value == SENSITIVE_CONFIG_VALUE_REDACTED

    # Build sources display
    sources_html = format_html_join(
        mark_safe("<br/>"),
        '<b style="color: {}">{}:</b> <code>{}</code>',
        ((color, source, value) for source, value, color in sources_info),
    )

    aliases = []

    if key in CONSTANTS_CONFIG:
        section_header = format_html(
            '[CONSTANTS]   &nbsp; <b><code style="color: lightgray">{}</code></b> &nbsp; <small>(read-only, hardcoded by ArchiveBox)</small>',
            key,
        )
    elif key in merged_config:
        section_header = format_html(
            'data / ArchiveBox.conf &nbsp; [{}]  &nbsp; <b><code style="color: lightgray">{}</code></b>',
            find_config_section(key),
            key,
        )
    else:
        section_header = format_html(
            '[DYNAMIC CONFIG]   &nbsp; <b><code style="color: lightgray">{}</code></b> &nbsp; <small>(read-only, calculated at runtime)</small>',
            key,
        )

    definition_url, definition_label = get_config_definition_link(key)
    redacted_message = (
        mark_safe(
            '<b style="color: red">Value is redacted for your security. (Passwords, secrets, API tokens, etc. cannot be viewed in the Web UI)</b><br/><br/>',
        )
        if is_redacted
        else ""
    )
    default_command_value = val.strip("'") if (val := find_config_default(key)) else str(final_value).strip("'")
    machine_config_link = (
        format_html('<br/><a href="{}">→ Edit <code>{}</code> in Machine.config for this server</a>', machine_admin_url, key)
        if machine_admin_url
        else ""
    )
    machine_config_tip = (
        format_html(
            '<br/><b>Tip:</b> To override <code>{}</code> on this machine, <a href="{}">edit the Machine.config field</a> and add:<br/><code>{}</code>',
            key,
            machine_admin_url,
            f'{{"{key}": "your_value_here"}}',
        )
        if machine_admin_url and key not in CONSTANTS_CONFIG
        else ""
    )

    section_data = cast(
        SectionData,
        {
            "name": section_header,
            "description": None,
            "fields": {
                "Key": key,
                "Type": find_config_type(key),
                "Value": final_value,
                "Currently read from": config_source,
            },
            "help_texts": {
                "Key": format_html(
                    """
                <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{}">Documentation</a>  &nbsp;
                <span style="display: {}">
                    Aliases: {}
                </span>
            """,
                    key.lower(),
                    "inline" if aliases else "none",
                    ", ".join(aliases),
                ),
                "Type": format_html(
                    """
                <a href="{}" target="_blank" rel="noopener noreferrer">
                    See full definition in <code>{}</code>...
                </a>
            """,
                    definition_url,
                    definition_label,
                ),
                "Value": format_html(
                    """
                {}
                <br/><hr/><br/>
                <b>Configuration Sources (highest priority first):</b><br/><br/>
                {}
                <br/><br/>
                <p style="display: {}">
                    <i>To change this value, edit <code>data/ArchiveBox.conf</code> or run:</i>
                    <br/><br/>
                    <code>archivebox config --set {}="{}"</code>
                </p>
            """,
                    redacted_message,
                    sources_html,
                    "block" if key in merged_config and key not in CONSTANTS_CONFIG else "none",
                    key,
                    default_command_value,
                ),
                "Currently read from": format_html(
                    """
                The value shown in the "Value" field comes from the <b>{}</b> source.
                <br/><br/>
                Priority order (highest to lowest):
                <ol>
                    <li><b style="color: purple">Machine</b> - Machine-specific overrides
                        {}
                    </li>
                    <li><b style="color: blue">Environment</b> - process defaults from environment variables</li>
                    <li><b style="color: green">File</b> - data/ArchiveBox.conf</li>
                    <li><b style="color: gray">Plugin Default</b> - Default value from plugin config.json</li>
                    <li><b style="color: gray">Default</b> - Default value from code</li>
                </ol>
                {}
            """,
                    config_source,
                    machine_config_link,
                    machine_config_tip,
                ),
            },
        },
    )

    return ItemContext(
        slug=key,
        title=key,
        data=[section_data],
    )
