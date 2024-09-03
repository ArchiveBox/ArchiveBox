from django.contrib import admin
from datetime import datetime
from django.utils.html import format_html

from api.auth import get_or_create_api_token

def get_abid_info(self, obj, request=None):
    try:
        return format_html(
            # URL Hash: <code style="font-size: 10px; user-select: all">{}</code><br/>
            '''
            <a href="{}" style="font-size: 16px; font-family: monospace; user-select: all; border-radius: 8px; background-color: #ddf; padding: 3px 5px; border: 1px solid #aaa; margin-bottom: 8px; display: inline-block; vertical-align: top;">{}</a> &nbsp; &nbsp; <a href="{}" style="color: limegreen; font-size: 0.9em; vertical-align: 1px; font-family: monospace;">📖 API DOCS</a>
            <br/><hr/>
            <div style="opacity: 0.8">
            &nbsp; &nbsp; <small style="opacity: 0.8">.abid: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px; user-select: all">{}</code></small><br/>
            &nbsp; &nbsp; <small style="opacity: 0.8">.abid.uuid: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px; user-select: all">{}</code></small><br/>
            &nbsp; &nbsp; <small style="opacity: 0.8">.id: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;&nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;<code style="font-size: 10px; user-select: all">{}</code></small><br/>
            <hr/>
            &nbsp; &nbsp; TS: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;<code style="font-size: 10px;"><b style="user-select: all">{}</b> &nbsp; {}</code> &nbsp; &nbsp; &nbsp;&nbsp; {}: <code style="user-select: all">{}</code><br/>
            &nbsp; &nbsp; URI: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px; "><b style="user-select: all">{}</b> &nbsp; &nbsp; {}</code> &nbsp;&nbsp; &nbsp; &nbsp; &nbsp;&nbsp; <span style="display:inline-block; vertical-align: -4px; width: 290px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{}: <code style="user-select: all">{}</code></span>
            &nbsp; SALT: &nbsp; <code style="font-size: 10px;"><b style="display:inline-block; user-select: all; width: 50px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{}</b></code><br/>
            &nbsp; &nbsp; SUBTYPE: &nbsp; &nbsp; &nbsp; <code style="font-size: 10px;"><b style="user-select: all">{}</b> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; {}</code> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; {}: <code style="user-select: all">{}</code><br/>
            &nbsp; &nbsp; RAND: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; <code style="font-size: 10px;"><b style="user-select: all">{}</b> &nbsp; &nbsp; &nbsp; {}</code> &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;  {}: <code style="user-select: all">{}</code>
            <br/><hr/>
            &nbsp; &nbsp; <small style="opacity: 0.5">.old_id: &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp; &nbsp;<code style="font-size: 10px; user-select: all">{}</code></small><br/>
            </div>
            ''',
            obj.api_url + (f'?api_key={get_or_create_api_token(request.user)}' if request and request.user else ''), obj.api_url, obj.api_docs_url,
            str(obj.abid),
            str(obj.ABID.uuid),
            str(obj.id),
            obj.ABID.ts, str(obj.ABID.uuid)[0:14], obj.abid_ts_src, obj.abid_values['ts'].isoformat() if isinstance(obj.abid_values['ts'], datetime) else obj.abid_values['ts'],
            obj.ABID.uri, str(obj.ABID.uuid)[14:26], obj.abid_uri_src, str(obj.abid_values['uri']),
            obj.ABID.uri_salt,
            obj.ABID.subtype, str(obj.ABID.uuid)[26:28], obj.abid_subtype_src, str(obj.abid_values['subtype']),
            obj.ABID.rand, str(obj.ABID.uuid)[28:36], obj.abid_rand_src, str(obj.abid_values['rand'])[-7:],
            str(getattr(obj, 'old_id', '')),
        )
    except Exception as e:
        return str(e)


class ABIDModelAdmin(admin.ModelAdmin):
    list_display = ('created', 'created_by', 'abid', '__str__')
    sort_fields = ('created', 'created_by', 'abid', '__str__')
    readonly_fields = ('created', 'modified', '__str__', 'API')

    def API(self, obj):
        return get_abid_info(self, obj, request=self.request)

    def queryset(self, request):
        self.request = request
        return super().queryset(request)
    
    def change_view(self, request, object_id, form_url="", extra_context=None):
        self.request = request
        return super().change_view(request, object_id, form_url, extra_context)

    def get_form(self, request, obj=None, **kwargs):
        self.request = request
        form = super().get_form(request, obj, **kwargs)
        if 'created_by' in form.base_fields:
            form.base_fields['created_by'].initial = request.user
        return form

    # def save_model(self, request, obj, form, change):
    #     if getattr(obj, 'created_by_id', None) in (None, get_or_create_system_user_pk()):
    #         obj.created_by = request.user
    #     obj.save()
