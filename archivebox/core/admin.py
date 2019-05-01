from django.contrib import admin

from core.models import Snapshot


class SnapshotAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'short_url', 'title', 'is_archived', 'num_outputs', 'added', 'updated', 'url_hash')
    readonly_fields = ('num_outputs', 'is_archived', 'added', 'updated', 'bookmarked')
    fields = ('url', 'timestamp', 'title', 'tags', *readonly_fields)

    def short_url(self, obj):
        return obj.url[:64]

    def updated(self, obj):
        return obj.isoformat()

admin.site.register(Snapshot, SnapshotAdmin)
