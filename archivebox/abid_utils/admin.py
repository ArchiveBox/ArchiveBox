from django.contrib import admin


class ABIDModelAdmin(admin.ModelAdmin):
    list_display = ('created', 'created_by', 'abid', '__str__')
    sort_fields = ('created', 'created_by', 'abid', '__str__')
    readonly_fields = ('abid', 'created', '__str__')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if 'created_by' in form.base_fields:
            form.base_fields['created_by'].initial = request.user
        return form

    # def save_model(self, request, obj, form, change):
    #     if getattr(obj, 'created_by_id', None) in (None, get_or_create_system_user_pk()):
    #         obj.created_by = request.user
    #     obj.save()
