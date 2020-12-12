from django import template
from django.urls import reverse
from django.contrib.admin.templatetags.base import InclusionAdminNode
from django.templatetags.static import static


from typing import Union

from core.models import ArchiveResult

register = template.Library()

@register.simple_tag
def snapshot_image(snapshot):
    result = ArchiveResult.objects.filter(snapshot=snapshot, extractor='screenshot', status='succeeded').first()
    if result:
        return reverse('LinkAssets', args=[f'{str(snapshot.timestamp)}/{result.output}'])
    
    return static('archive.png')

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
