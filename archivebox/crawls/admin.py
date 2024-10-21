__package__ = 'archivebox.crawls'

import abx

from abid_utils.admin import ABIDModelAdmin

from crawls.models import Crawl



class CrawlAdmin(ABIDModelAdmin):
    list_display = ('abid', 'created_at', 'created_by', 'depth', 'parser', 'urls')
    sort_fields = ('abid', 'created_at', 'created_by', 'depth', 'parser', 'urls')
    search_fields = ('abid', 'created_by__username', 'depth', 'parser', 'urls')
    
    readonly_fields = ('created_at', 'modified_at', 'abid_info')
    fields = ('urls', 'depth', 'parser', 'created_by', *readonly_fields)

    list_filter = ('depth', 'parser', 'created_by')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]



@abx.hookimpl
def register_admin(admin_site):
    admin_site.register(Crawl, CrawlAdmin)
