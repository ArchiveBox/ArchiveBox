"""Base admin classes for models using UUIDv7."""

__package__ = 'archivebox.base_models'

from django.contrib import admin
from django.utils.html import format_html, mark_safe
from django_object_actions import DjangoObjectActions


class ConfigEditorMixin:
    """
    Mixin for admin classes with a config JSON field.

    Provides a readonly field that shows available config options
    from all discovered plugin schemas.
    """

    @admin.display(description='Available Config Options')
    def available_config_options(self, obj):
        """Show documentation for available config keys."""
        try:
            from archivebox.hooks import discover_plugin_configs
            plugin_configs = discover_plugin_configs()
        except ImportError:
            return format_html('<i>Plugin config system not available</i>')

        html_parts = [
            '<details>',
            '<summary style="cursor: pointer; font-weight: bold; padding: 4px;">',
            'Click to see available config keys ({})</summary>'.format(
                sum(len(s.get('properties', {})) for s in plugin_configs.values())
            ),
            '<div style="max-height: 400px; overflow-y: auto; padding: 8px; background: #f8f8f8; border-radius: 4px; font-family: monospace; font-size: 11px;">',
        ]

        for plugin_name, schema in sorted(plugin_configs.items()):
            properties = schema.get('properties', {})
            if not properties:
                continue

            html_parts.append(f'<div style="margin: 8px 0;"><strong style="color: #333;">{plugin_name}</strong></div>')
            html_parts.append('<table style="width: 100%; border-collapse: collapse; margin-bottom: 12px;">')
            html_parts.append('<tr style="background: #eee;"><th style="text-align: left; padding: 4px;">Key</th><th style="text-align: left; padding: 4px;">Type</th><th style="text-align: left; padding: 4px;">Default</th><th style="text-align: left; padding: 4px;">Description</th></tr>')

            for key, prop in sorted(properties.items()):
                prop_type = prop.get('type', 'string')
                default = prop.get('default', '')
                description = prop.get('description', '')

                # Truncate long defaults
                default_str = str(default)
                if len(default_str) > 30:
                    default_str = default_str[:27] + '...'

                html_parts.append(
                    f'<tr style="border-bottom: 1px solid #ddd;">'
                    f'<td style="padding: 4px; font-weight: bold;">{key}</td>'
                    f'<td style="padding: 4px; color: #666;">{prop_type}</td>'
                    f'<td style="padding: 4px; color: #666;">{default_str}</td>'
                    f'<td style="padding: 4px;">{description}</td>'
                    f'</tr>'
                )

            html_parts.append('</table>')

        html_parts.append('</div></details>')
        html_parts.append(
            '<p style="margin-top: 8px; color: #666; font-size: 11px;">'
            '<strong>Usage:</strong> Add key-value pairs in JSON format, e.g., '
            '<code>{"SAVE_WGET": false, "WGET_TIMEOUT": 120}</code>'
            '</p>'
        )

        return mark_safe(''.join(html_parts))


class BaseModelAdmin(DjangoObjectActions, admin.ModelAdmin):
    list_display = ('id', 'created_at', 'created_by')
    readonly_fields = ('id', 'created_at', 'modified_at')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'created_by' in form.base_fields:
            form.base_fields['created_by'].initial = request.user
        return form
