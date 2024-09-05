__package__ = 'archivebox.abid_utils'

from typing import Any
from datetime import datetime

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.shortcuts import redirect

from abid_utils.abid import ABID, abid_part_from_ts, abid_part_from_uri, abid_part_from_rand, abid_part_from_subtype

from api.auth import get_or_create_api_token

from ..util import parse_date

def highlight_diff(display_val: Any, compare_val: Any, invert: bool=False, color_same: str | None=None, color_diff: str | None=None):
    """highlight each character in red that differs with the char at the same index in compare_val"""

    display_val = str(display_val)
    compare_val = str(compare_val)

    if len(compare_val) < len(display_val):
        compare_val += ' ' * (len(display_val) - len(compare_val))

    similar_color, highlighted_color = color_same or 'inherit', color_diff or 'red'
    if invert:
        similar_color, highlighted_color = color_same or 'green', color_diff or 'inherit'

    return mark_safe(''.join(
        format_html('<span style="color: {};">{}</span>', highlighted_color, display_val[i])
        if display_val[i] != compare_val[i] else
        format_html('<span style="color: {};">{}</span>', similar_color, display_val[i])
        for i in range(len(display_val))
    ))

def get_abid_info(self, obj, request=None):
    try:
        #abid_diff = f' != obj.ABID: {highlight_diff(obj.ABID, obj.abid)} ❌' if str(obj.ABID) != str(obj.abid) else ' == .ABID ✅'

        fresh_abid = ABID(**obj.ABID_FRESH_HASHES)
        fresh_abid_diff = f'❌ != &nbsp; .fresh_abid: {highlight_diff(fresh_abid, obj.ABID)}' if str(fresh_abid) != str(obj.ABID) else '✅'
        fresh_uuid_diff = f'❌ != &nbsp; .fresh_uuid: {highlight_diff(fresh_abid.uuid, obj.ABID.uuid)}' if str(fresh_abid.uuid) != str(obj.ABID.uuid) else '✅'

        id_pk_diff = f'❌ !=  .pk: {highlight_diff(obj.pk, obj.id)}' if str(obj.pk) != str(obj.id) else '✅'

        fresh_ts = parse_date(obj.ABID_FRESH_VALUES['ts']) or None
        ts_diff = f'❌ != {highlight_diff( obj.ABID_FRESH_HASHES["ts"], obj.ABID.ts)}' if  obj.ABID_FRESH_HASHES["ts"] != obj.ABID.ts else '✅'

        derived_uri = obj.ABID_FRESH_HASHES['uri']
        uri_diff = f'❌ != {highlight_diff(derived_uri, obj.ABID.uri)}' if derived_uri != obj.ABID.uri else '✅'

        derived_subtype = obj.ABID_FRESH_HASHES['subtype']
        subtype_diff = f'❌ != {highlight_diff(derived_subtype, obj.ABID.subtype)}' if derived_subtype != obj.ABID.subtype else '✅'

        derived_rand = obj.ABID_FRESH_HASHES['rand']
        rand_diff = f'❌ != {highlight_diff(derived_rand, obj.ABID.rand)}' if derived_rand != obj.ABID.rand else '✅'

        return format_html(
            # URL Hash: <code style="font-size: 10px; user-select: all">{}</code><br/>
            '''
            <a href="{}" style="font-size: 16px; font-family: monospace; user-select: all; border-radius: 8px; background-color: #ddf; padding: 3px 5px; border: 1px solid #aaa; margin-bottom: 8px; display: inline-block; vertical-align: top;">{}</a> &nbsp; &nbsp; <a href="{}" style="color: limegreen; font-size: 0.9em; vertical-align: 1px; font-family: monospace;">📖 API DOCS</a>
            <br/><hr/>
            <div style="opacity: 0.8">
            &nbsp; &nbsp; <small style="opacity: 0.8">.id: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;<code style="font-size: 10px; user-select: all">{}</code> &nbsp; &nbsp; {}</small><br/>
            &nbsp; &nbsp; <small style="opacity: 0.8">.abid.uuid: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px; user-select: all">{}</code> &nbsp; &nbsp; {}</small><br/>
            &nbsp; &nbsp; <small style="opacity: 0.8">.abid: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px; user-select: all">{}</code> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; {}</small><br/>
            <hr/>
            &nbsp; &nbsp; TS: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;<code style="font-size: 10px;"><b style="user-select: all">{}</b> &nbsp; {}</code> &nbsp; &nbsp; &nbsp;&nbsp; <code style="font-size: 10px;"><b>{}</b></code> {}: <code style="user-select: all">{}</code><br/>
            &nbsp; &nbsp; URI: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px;"><b style="user-select: all">{}</b> &nbsp; &nbsp; {}</code> &nbsp;&nbsp; &nbsp; &nbsp; &nbsp;&nbsp; <code style="font-size: 10px;"><b>{}</b></code> <span style="display:inline-block; vertical-align: -4px; width: 330px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{}: <code style="user-select: all">{}</code></span><br/>
            &nbsp; &nbsp; SUBTYPE: &nbsp; &nbsp; &nbsp; <code style="font-size: 10px;"><b style="user-select: all">{}</b> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; {}</code> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px;"><b>{}</b></code> {}: <code style="user-select: all">{}</code><br/>
            &nbsp; &nbsp; RAND: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px;"><b style="user-select: all">{}</b> &nbsp; &nbsp; &nbsp; {}</code> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px;"><b>{}</b></code> {}: <code style="user-select: all">{}</code></code>
            <br/><hr/>
            <span style="color: #f375a0">{}</span> <code style="color: red"><b>{}</b></code>
            </div>
            ''',
            obj.api_url + (f'?api_key={get_or_create_api_token(request.user)}' if request and request.user else ''), obj.api_url, obj.api_docs_url,
            highlight_diff(obj.id, obj.ABID.uuid, invert=True), mark_safe(id_pk_diff),
            highlight_diff(obj.ABID.uuid, obj.id, invert=True), mark_safe(fresh_uuid_diff),
            highlight_diff(obj.abid, fresh_abid), mark_safe(fresh_abid_diff),
            # str(fresh_abid.uuid), mark_safe(fresh_uuid_diff),
            # str(fresh_abid), mark_safe(fresh_abid_diff),
            highlight_diff(obj.ABID.ts,  obj.ABID_FRESH_HASHES['ts']), highlight_diff(str(obj.ABID.uuid)[0:14], str(fresh_abid.uuid)[0:14]), mark_safe(ts_diff), obj.abid_ts_src, fresh_ts and fresh_ts.isoformat(),
            highlight_diff(obj.ABID.uri, derived_uri), highlight_diff(str(obj.ABID.uuid)[14:26], str(fresh_abid.uuid)[14:26]), mark_safe(uri_diff), obj.abid_uri_src, str(obj.ABID_FRESH_VALUES['uri']),
            highlight_diff(obj.ABID.subtype, derived_subtype), highlight_diff(str(obj.ABID.uuid)[26:28], str(fresh_abid.uuid)[26:28]), mark_safe(subtype_diff), obj.abid_subtype_src, str(obj.ABID_FRESH_VALUES['subtype']),
            highlight_diff(obj.ABID.rand, derived_rand), highlight_diff(str(obj.ABID.uuid)[28:36], str(fresh_abid.uuid)[28:36]), mark_safe(rand_diff), obj.abid_rand_src, str(obj.ABID_FRESH_VALUES['rand'])[-7:],
            f'Some values the ABID depends on have changed since the ABID was issued:' if obj.ABID_FRESH_DIFFS else '',
            ", ".join(diff['abid_src'] for diff in obj.ABID_FRESH_DIFFS.values()),
        )
    except Exception as e:
        # import ipdb; ipdb.set_trace()
        return str(e)


class ABIDModelAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'created_by', 'abid', '__str__')
    sort_fields = ('created_at', 'created_by', 'abid', '__str__')
    readonly_fields = ('created_at', 'modified_at', '__str__', 'abid_info')

    @admin.display(description='API Identifiers')
    def abid_info(self, obj):
        return get_abid_info(self, obj, request=self.request)

    def queryset(self, request):
        self.request = request
        return super().queryset(request)
    
    def change_view(self, request, object_id, form_url="", extra_context=None):
        self.request = request

        if object_id:
            try:
                object_uuid = str(self.model.objects.only('pk').get(abid=self.model.abid_prefix + object_id.split('_', 1)[-1]).pk)
                if object_id != object_uuid:
                    return redirect(self.request.path.replace(object_id, object_uuid), permanent=False)
            except (self.model.DoesNotExist, ValidationError):
                pass

        return super().change_view(request, object_id, form_url, extra_context)

    def get_form(self, request, obj=None, **kwargs):
        self.request = request
        form = super().get_form(request, obj, **kwargs)
        if 'created_by' in form.base_fields:
            form.base_fields['created_by'].initial = request.user
        return form

    def save_model(self, request, obj, form, change):
        old_abid = obj.abid
        super().save_model(request, obj, form, change)
        new_abid = obj.abid
        if new_abid != old_abid:
            messages.warning(request, f"The object's ABID has been updated! {old_abid} -> {new_abid} (any references to the old ABID will need to be updated)")
