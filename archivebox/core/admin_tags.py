__package__ = 'archivebox.core'

from urllib.parse import quote

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.options import IS_POPUP_VAR
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from archivebox.base_models.admin import BaseModelAdmin
from archivebox.core.models import SnapshotTag, Tag
from archivebox.core.tag_utils import (
    TAG_HAS_SNAPSHOTS_CHOICES,
    TAG_SORT_CHOICES,
    build_tag_cards,
    get_tag_creator_choices,
    get_tag_year_choices,
    normalize_created_by_filter,
    normalize_created_year_filter,
    normalize_has_snapshots_filter,
    normalize_tag_sort,
)
from archivebox.core.host_utils import build_snapshot_url


class TagInline(admin.TabularInline):
    model = SnapshotTag
    fields = ('id', 'tag')
    extra = 1
    max_num = 1000
    autocomplete_fields = (
        'tag',
    )


class TagAdminForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={
                'placeholder': 'research, receipts, product-design...',
                'autocomplete': 'off',
                'spellcheck': 'false',
                'data-tag-name-input': '1',
            }),
        }

    def clean_name(self):
        name = (self.cleaned_data.get('name') or '').strip()
        if not name:
            raise forms.ValidationError('Tag name is required.')
        return name


class TagAdmin(BaseModelAdmin):
    form = TagAdminForm
    change_list_template = 'admin/core/tag/change_list.html'
    change_form_template = 'admin/core/tag/change_form.html'
    list_display = ('name', 'num_snapshots', 'created_at', 'created_by')
    list_filter = ('created_at', 'created_by')
    search_fields = ('id', 'name', 'slug')
    readonly_fields = ('slug', 'id', 'created_at', 'modified_at', 'snapshots')
    actions = ['delete_selected']
    ordering = ['name', 'id']

    fieldsets = (
        ('Tag', {
            'fields': ('name', 'slug'),
            'classes': ('card',),
        }),
        ('Metadata', {
            'fields': ('id', 'created_by', 'created_at', 'modified_at'),
            'classes': ('card',),
        }),
        ('Recent Snapshots', {
            'fields': ('snapshots',),
            'classes': ('card', 'wide'),
        }),
    )

    add_fieldsets = (
        ('Tag', {
            'fields': ('name',),
            'classes': ('card', 'wide'),
        }),
        ('Metadata', {
            'fields': ('created_by',),
            'classes': ('card',),
        }),
    )

    def get_fieldsets(self, request: HttpRequest, obj: Tag | None = None):
        return self.fieldsets if obj else self.add_fieldsets

    def changelist_view(self, request: HttpRequest, extra_context=None):
        query = (request.GET.get('q') or '').strip()
        sort = normalize_tag_sort((request.GET.get('sort') or 'created_desc').strip())
        created_by = normalize_created_by_filter((request.GET.get('created_by') or '').strip())
        year = normalize_created_year_filter((request.GET.get('year') or '').strip())
        has_snapshots = normalize_has_snapshots_filter((request.GET.get('has_snapshots') or 'all').strip())
        extra_context = {
            **(extra_context or {}),
            'initial_query': query,
            'initial_sort': sort,
            'initial_created_by': created_by,
            'initial_year': year,
            'initial_has_snapshots': has_snapshots,
            'tag_sort_choices': TAG_SORT_CHOICES,
            'tag_has_snapshots_choices': TAG_HAS_SNAPSHOTS_CHOICES,
            'tag_created_by_choices': get_tag_creator_choices(),
            'tag_year_choices': get_tag_year_choices(),
            'initial_tag_cards': build_tag_cards(
                query=query,
                request=request,
                sort=sort,
                created_by=created_by,
                year=year,
                has_snapshots=has_snapshots,
            ),
            'tag_search_api_url': reverse('api-1:search_tags'),
            'tag_create_api_url': reverse('api-1:tags_create'),
        }
        return super().changelist_view(request, extra_context=extra_context)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        current_name = (request.POST.get('name') or '').strip()
        if not current_name and obj:
            current_name = obj.name

        similar_tag_cards = build_tag_cards(query=current_name, request=request, limit=12) if current_name else build_tag_cards(request=request, limit=12)
        if obj:
            similar_tag_cards = [card for card in similar_tag_cards if card['id'] != obj.pk]

        context.update({
            'tag_search_api_url': reverse('api-1:search_tags'),
            'tag_similar_cards': similar_tag_cards,
            'tag_similar_query': current_name,
        })
        return super().render_change_form(request, context, add=add, change=change, form_url=form_url, obj=obj)

    def response_add(self, request: HttpRequest, obj: Tag, post_url_continue=None):
        if IS_POPUP_VAR in request.POST or '_continue' in request.POST or '_addanother' in request.POST:
            return super().response_add(request, obj, post_url_continue=post_url_continue)

        self.message_user(request, f'Tag "{obj.name}" saved.', level=messages.SUCCESS)
        return self._redirect_to_changelist(obj.name)

    def response_change(self, request: HttpRequest, obj: Tag):
        if IS_POPUP_VAR in request.POST or '_continue' in request.POST or '_addanother' in request.POST or '_saveasnew' in request.POST:
            return super().response_change(request, obj)

        self.message_user(request, f'Tag "{obj.name}" updated.', level=messages.SUCCESS)
        return self._redirect_to_changelist(obj.name)

    def _redirect_to_changelist(self, query: str = '') -> HttpResponseRedirect:
        changelist_url = reverse('admin:core_tag_changelist')
        if query:
            changelist_url = f'{changelist_url}?q={quote(query)}'
        return HttpResponseRedirect(changelist_url)

    @admin.display(description='Snapshots')
    def snapshots(self, tag: Tag):
        snapshots = tag.snapshot_set.select_related('crawl__created_by').order_by('-downloaded_at', '-created_at', '-pk')[:10]
        total_count = tag.snapshot_set.count()
        if not snapshots:
            return mark_safe(
                f'<p style="margin:0;color:#64748b;">No snapshots use this tag yet. '
                f'<a href="/admin/core/snapshot/?tags__id__exact={tag.id}">Open filtered snapshot list</a>.</p>'
            )

        cards = []
        for snapshot in snapshots:
            title = (snapshot.title or '').strip() or snapshot.url
            cards.append(format_html(
                '''
                <a href="{}" style="display:flex;align-items:center;gap:10px;padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;background:#fff;text-decoration:none;color:#0f172a;">
                    <img src="{}" alt="" style="width:18px;height:18px;border-radius:4px;flex:0 0 auto;" onerror="this.style.display='none'">
                    <span style="min-width:0;">
                        <strong style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{}</strong>
                        <code style="display:block;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{}</code>
                    </span>
                </a>
                ''',
                reverse('admin:core_snapshot_change', args=[snapshot.pk]),
                build_snapshot_url(str(snapshot.pk), 'favicon.ico'),
                title[:120],
                snapshot.url[:120],
            ))

        cards.append(format_html(
            '<a href="/admin/core/snapshot/?tags__id__exact={}" style="display:inline-flex;margin-top:10px;font-weight:600;">View all {} tagged snapshots</a>',
            tag.id,
            total_count,
        ))
        return mark_safe('<div style="display:grid;gap:10px;">' + ''.join(cards) + '</div>')

    @admin.display(description='Snapshots', ordering='num_snapshots')
    def num_snapshots(self, tag: Tag):
        count = getattr(tag, 'num_snapshots', tag.snapshot_set.count())
        return format_html(
            '<a href="/admin/core/snapshot/?tags__id__exact={}">{} total</a>',
            tag.id,
            count,
        )


def register_admin(admin_site):
    admin_site.register(Tag, TagAdmin)
