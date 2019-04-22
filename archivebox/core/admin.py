from django.contrib import admin

from .models import Page

class PageAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'short_url', 'title', 'is_archived', 'num_outputs', 'added', 'updated', 'url_hash')

    def short_url(self, obj):
        return obj.url[:64]

admin.site.register(Page, PageAdmin)
