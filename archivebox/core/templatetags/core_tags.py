from django import template
from django.contrib.admin.templatetags.base import InclusionAdminNode
from django.utils.safestring import mark_safe
from django.utils.html import escape

from typing import Union
from pathlib import Path

from archivebox.hooks import (
    get_plugin_icon, get_plugin_template, get_plugin_name,
)


register = template.Library()

@register.filter(name='split')
def split(value, separator: str=','):
    return (value or '').split(separator)

@register.filter
def file_size(num_bytes: Union[int, float]) -> str:
    for count in ['Bytes','KB','MB','GB']:
        if num_bytes > -1024.0 and num_bytes < 1024.0:
            return '%3.1f %s' % (num_bytes, count)
        num_bytes /= 1024.0
    return '%3.1f %s' % (num_bytes, 'TB')

def result_list(cl):
    """
    Monkey patched result
    """
    num_sorted_fields = 0
    return {
        'cl': cl,
        'num_sorted_fields': num_sorted_fields,
        'results': cl.result_list,
    }

@register.tag(name='snapshots_grid')
def result_list_tag(parser, token):
    return InclusionAdminNode(
        parser, token,
        func=result_list,
        template_name='snapshots_grid.html',
        takes_context=False,
    )

@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    dict_ = context['request'].GET.copy()
    dict_.update(**kwargs)
    return dict_.urlencode()


@register.simple_tag
def plugin_icon(plugin: str) -> str:
    """
    Render the icon for a plugin.

    Usage: {% plugin_icon "screenshot" %}
    """
    icon_html = get_plugin_icon(plugin)
    return mark_safe(
        f'<span class="abx-plugin-icon" style="display:inline-flex; width:20px; height:20px; align-items:center; justify-content:center;">{icon_html}</span>'
    )


@register.simple_tag(takes_context=True)
def plugin_card(context, result) -> str:
    """
    Render the card template for an archive result.

    Usage: {% plugin_card result %}

    Context variables passed to template:
        - result: ArchiveResult object
        - snapshot: Parent Snapshot object
        - output_path: Path to output relative to snapshot dir (from embed_path())
        - plugin: Plugin base name
    """
    plugin = get_plugin_name(result.plugin)
    template_str = get_plugin_template(plugin, 'card')

    # Use embed_path() for the display path
    output_path = result.embed_path() if hasattr(result, 'embed_path') else ''

    icon_html = get_plugin_icon(plugin)

    output_lower = (output_path or '').lower()
    text_preview_exts = ('.json', '.jsonl', '.txt', '.csv', '.tsv', '.xml', '.yml', '.yaml', '.md', '.log')
    force_text_preview = output_lower.endswith(text_preview_exts)

    # Create a mini template and render it with context
    try:
        if template_str and output_path and str(output_path).strip() not in ('.', '/', './') and not force_text_preview:
            tpl = template.Template(template_str)
            ctx = template.Context({
                'result': result,
                'snapshot': result.snapshot,
                'output_path': output_path,
                'plugin': plugin,
                'plugin_icon': icon_html,
            })
            rendered = tpl.render(ctx)
            # Only return non-empty content (strip whitespace to check)
            if rendered.strip():
                return mark_safe(rendered)
    except Exception:
        pass

    if force_text_preview and output_path and str(output_path).strip() not in ('.', '/', './'):
        output_file = Path(output_path)
        if not output_file.is_absolute():
            output_file = Path(result.snapshot_dir) / output_path
        try:
            output_file = output_file.resolve()
            snap_dir = Path(result.snapshot_dir).resolve()
            if snap_dir not in output_file.parents and output_file != snap_dir:
                output_file = None
        except Exception:
            output_file = None
        if output_file and output_file.exists() and output_file.is_file():
            try:
                with output_file.open('rb') as f:
                    raw = f.read(4096)
                text = raw.decode('utf-8', errors='replace').strip()
                if text:
                    lines = text.splitlines()[:6]
                    snippet = '\n'.join(lines)
                    escaped = escape(snippet)
                    preview = (
                        f'<div class="thumbnail-text" data-plugin="{plugin}" data-compact="1">'
                        f'<div class="thumbnail-text-header">'
                        f'<span class="thumbnail-compact-icon">{icon_html}</span>'
                        f'<span class="thumbnail-text-title">{plugin}</span>'
                        f'</div>'
                        f'<pre class="thumbnail-text-pre">{escaped}</pre>'
                        f'</div>'
                    )
                    return mark_safe(preview)
            except Exception:
                pass

    if output_lower.endswith(text_preview_exts):
        fallback_label = 'text'
    else:
        fallback_label = 'output'

    fallback = (
        f'<div class="thumbnail-compact" data-plugin="{plugin}" data-compact="1">'
        f'<span class="thumbnail-compact-icon">{icon_html}</span>'
        f'<span class="thumbnail-compact-label">{plugin}</span>'
        f'<span class="thumbnail-compact-meta">{fallback_label}</span>'
        f'</div>'
    )
    return mark_safe(fallback)


@register.simple_tag(takes_context=True)
def plugin_full(context, result) -> str:
    """
    Render the full template for an archive result.

    Usage: {% plugin_full result %}
    """
    plugin = get_plugin_name(result.plugin)
    template_str = get_plugin_template(plugin, 'full')

    if not template_str:
        return ''

    output_path = result.embed_path() if hasattr(result, 'embed_path') else ''

    try:
        tpl = template.Template(template_str)
        ctx = template.Context({
            'result': result,
            'snapshot': result.snapshot,
            'output_path': output_path,
            'plugin': plugin,
        })
        rendered = tpl.render(ctx)
        # Only return non-empty content (strip whitespace to check)
        if rendered.strip():
            return mark_safe(rendered)
        return ''
    except Exception:
        return ''




@register.filter
def plugin_name(value: str) -> str:
    """
    Get the base name of a plugin (strips numeric prefix).

    Usage: {{ result.plugin|plugin_name }}
    """
    return get_plugin_name(value)
