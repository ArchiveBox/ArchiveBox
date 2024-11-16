__package__ = 'archivebox.seeds'

import abx

from django.utils.html import format_html_join, format_html

from abid_utils.admin import ABIDModelAdmin

from archivebox import DATA_DIR

from seeds.models import Seed



class SeedAdmin(ABIDModelAdmin):
    list_display = ('abid', 'created_at', 'created_by', 'label', 'notes', 'uri', 'extractor', 'tags_str', 'crawls', 'num_crawls', 'num_snapshots')
    sort_fields = ('abid', 'created_at', 'created_by', 'label', 'notes', 'uri', 'extractor', 'tags_str')
    search_fields = ('abid', 'created_by__username', 'label', 'notes', 'uri', 'extractor', 'tags_str')
    
    readonly_fields = ('created_at', 'modified_at', 'abid_info', 'scheduled_crawls', 'crawls', 'snapshots', 'contents')
    fields = ('label', 'notes', 'uri', 'extractor', 'tags_str', 'config', 'created_by', *readonly_fields)

    list_filter = ('extractor', 'created_by')
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    def num_crawls(self, obj):
        return obj.crawl_set.count()

    def num_snapshots(self, obj):
        return obj.snapshot_set.count()

    def scheduled_crawls(self, obj):
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (scheduledcrawl.admin_change_url, scheduledcrawl)
            for scheduledcrawl in  obj.scheduled_crawl_set.all().order_by('-created_at')[:20]
        )) or format_html('<i>No Scheduled Crawls yet...</i>')

    def crawls(self, obj):
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (crawl.admin_change_url, crawl)
            for crawl in obj.crawl_set.all().order_by('-created_at')[:20]
        )) or format_html('<i>No Crawls yet...</i>')

    def snapshots(self, obj):
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (snapshot.admin_change_url, snapshot)
            for snapshot in obj.snapshot_set.all().order_by('-created_at')[:20]
        )) or format_html('<i>No Snapshots yet...</i>')

    def contents(self, obj):
        if obj.uri.startswith('file:///data/'):
            source_file = DATA_DIR / obj.uri.replace('file:///data/', '', 1)
            contents = ""
            try:
                contents = source_file.read_text().strip()[:14_000]
            except Exception as e:
                contents = f'Error reading {source_file}: {e}'
                
            return format_html('<b><code>{}</code>:</b><br/><pre>{}</pre>', source_file, contents)
        
        return format_html('See URLs here: <a href="{}">{}</a>', obj.uri, obj.uri)


@abx.hookimpl
def register_admin(admin_site):
    admin_site.register(Seed, SeedAdmin)
