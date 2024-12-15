__package__ = 'archivebox.crawls'

from django.utils.html import format_html, format_html_join
from django.contrib import admin

from archivebox import DATA_DIR

from archivebox.base_models.admin import ABIDModelAdmin

from core.models import Snapshot
from crawls.models import Seed, Crawl, CrawlSchedule


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




class CrawlAdmin(ABIDModelAdmin):
    list_display = ('abid', 'created_at', 'created_by', 'max_depth', 'label', 'notes', 'seed_str', 'schedule_str', 'status', 'retry_at', 'num_snapshots')
    sort_fields = ('abid', 'created_at', 'created_by', 'max_depth', 'label', 'notes', 'seed_str', 'schedule_str', 'status', 'retry_at')
    search_fields = ('abid', 'created_by__username', 'max_depth', 'label', 'notes', 'seed_id', 'seed__abid', 'schedule_id', 'schedule__abid', 'status', 'seed__uri')
    
    readonly_fields = ('created_at', 'modified_at', 'abid_info', 'snapshots', 'seed_contents')
    fields = ('label', 'notes', 'urls', 'status', 'retry_at', 'max_depth', 'seed', 'schedule', 'created_by', *readonly_fields)

    list_filter = ('max_depth', 'seed', 'schedule', 'created_by', 'status', 'retry_at')
    ordering = ['-created_at', '-retry_at']
    list_per_page = 100
    actions = ["delete_selected"]
    
    def num_snapshots(self, obj):
        return obj.snapshot_set.count()

    def snapshots(self, obj):
        return format_html_join('<br/>', '<a href="{}">{}</a>', (
            (snapshot.admin_change_url, snapshot)
            for snapshot in obj.snapshot_set.all().order_by('-created_at')[:20]
        )) or format_html('<i>No Snapshots yet...</i>')
        
    @admin.display(description='Schedule', ordering='schedule')
    def schedule_str(self, obj):
        if not obj.schedule:
            return format_html('<i>None</i>')
        return format_html('<a href="{}">{}</a>', obj.schedule.admin_change_url, obj.schedule)
    
    @admin.display(description='Seed', ordering='seed')
    def seed_str(self, obj):
        if not obj.seed:
            return format_html('<i>None</i>')
        return format_html('<a href="{}">{}</a>', obj.seed.admin_change_url, obj.seed)
    
    def seed_contents(self, obj):
        if not (obj.seed and obj.seed.uri):
            return format_html('<i>None</i>')
        
        if obj.seed.uri.startswith('file:///data/'):
            source_file = DATA_DIR / obj.seed.uri.replace('file:///data/', '', 1)
            contents = ""
            try:
                contents = source_file.read_text().strip()[:14_000]
            except Exception as e:
                contents = f'Error reading {source_file}: {e}'
                
            return format_html('<b><code>{}</code>:</b><br/><pre>{}</pre>', source_file, contents)
        
        return format_html('See URLs here: <a href="{}">{}</a>', obj.seed.uri, obj.seed.uri)



class CrawlScheduleAdmin(ABIDModelAdmin):
    list_display = ('abid', 'created_at', 'created_by', 'label', 'notes', 'template_str', 'crawls', 'num_crawls', 'num_snapshots')
    sort_fields = ('abid', 'created_at', 'created_by', 'label', 'notes', 'template_str')
    search_fields = ('abid', 'created_by__username', 'label', 'notes', 'schedule_id', 'schedule__abid', 'template_id', 'template__abid', 'template__seed__uri')
    
    readonly_fields = ('created_at', 'modified_at', 'abid_info', 'crawls', 'snapshots')
    fields = ('label', 'notes', 'schedule', 'template', 'created_by', *readonly_fields)

    list_filter = ('created_by',)
    ordering = ['-created_at']
    list_per_page = 100
    actions = ["delete_selected"]

    @admin.display(description='Template', ordering='template')
    def template_str(self, obj):
        return format_html('<a href="{}">{}</a>', obj.template.admin_change_url, obj.template)

    def num_crawls(self, obj):
        return obj.crawl_set.count()

    def num_snapshots(self, obj):
        return obj.snapshot_set.count()

    def crawls(self, obj):
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (crawl.admin_change_url, crawl)
            for crawl in obj.crawl_set.all().order_by('-created_at')[:20]
        )) or format_html('<i>No Crawls yet...</i>')
    
    def snapshots(self, obj):
        crawl_ids = obj.crawl_set.values_list('pk', flat=True)
        return format_html_join('<br/>', ' - <a href="{}">{}</a>', (
            (snapshot.admin_change_url, snapshot)
            for snapshot in Snapshot.objects.filter(crawl_id__in=crawl_ids).order_by('-created_at')[:20]
        )) or format_html('<i>No Snapshots yet...</i>')


def register_admin(admin_site):
    admin_site.register(Seed, SeedAdmin)
    admin_site.register(Crawl, CrawlAdmin)
    admin_site.register(CrawlSchedule, CrawlScheduleAdmin)
