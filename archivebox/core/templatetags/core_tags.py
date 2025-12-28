from django import template
from django.contrib.admin.templatetags.base import InclusionAdminNode
from django.utils.safestring import mark_safe

from typing import Union

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
    return mark_safe(get_plugin_icon(plugin))


@register.simple_tag(takes_context=True)
def plugin_thumbnail(context, result) -> str:
    """
    Render the thumbnail template for an archive result.

    Usage: {% plugin_thumbnail result %}

    Context variables passed to template:
        - result: ArchiveResult object
        - snapshot: Parent Snapshot object
        - output_path: Path to output relative to snapshot dir (from embed_path())
        - plugin: Plugin base name
    """
    plugin = get_plugin_name(result.plugin)
    template_str = get_plugin_template(plugin, 'thumbnail')

    if not template_str:
        return ''

    # Use embed_path() for the display path (includes canonical paths)
    output_path = result.embed_path() if hasattr(result, 'embed_path') else (result.output_str or '')

    # Create a mini template and render it with context
    try:
        tpl = template.Template(template_str)
        ctx = template.Context({
            'result': result,
            'snapshot': result.snapshot,
            'output_path': output_path,
            'plugin': plugin,
        })
        return mark_safe(tpl.render(ctx))
    except Exception:
        return ''


@register.simple_tag(takes_context=True)
def plugin_embed(context, result) -> str:
    """
    Render the embed iframe template for an archive result.

    Usage: {% plugin_embed result %}
    """
    plugin = get_plugin_name(result.plugin)
    template_str = get_plugin_template(plugin, 'embed')

    if not template_str:
        return ''

    output_path = result.embed_path() if hasattr(result, 'embed_path') else (result.output_str or '')

    try:
        tpl = template.Template(template_str)
        ctx = template.Context({
            'result': result,
            'snapshot': result.snapshot,
            'output_path': output_path,
            'plugin': plugin,
        })
        return mark_safe(tpl.render(ctx))
    except Exception:
        return ''


@register.simple_tag(takes_context=True)
def plugin_fullscreen(context, result) -> str:
    """
    Render the fullscreen template for an archive result.

    Usage: {% plugin_fullscreen result %}
    """
    plugin = get_plugin_name(result.plugin)
    template_str = get_plugin_template(plugin, 'fullscreen')

    if not template_str:
        return ''

    output_path = result.embed_path() if hasattr(result, 'embed_path') else (result.output_str or '')

    try:
        tpl = template.Template(template_str)
        ctx = template.Context({
            'result': result,
            'snapshot': result.snapshot,
            'output_path': output_path,
            'plugin': plugin,
        })
        return mark_safe(tpl.render(ctx))
    except Exception:
        return ''


@register.filter
def plugin_name(value: str) -> str:
    """
    Get the base name of a plugin (strips numeric prefix).

    Usage: {{ result.plugin|plugin_name }}
    """
    return get_plugin_name(value)
