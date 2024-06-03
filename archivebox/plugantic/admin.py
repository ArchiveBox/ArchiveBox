# from django.contrib import admin
# from django import forms

# from django_jsonform.widgets import JSONFormWidget

# from django_pydantic_field.v2.fields import PydanticSchemaField

# from .models import CustomPlugin


# class PluginForm(forms.ModelForm):
#     class Meta:
#         model = CustomPlugin
#         fields = '__all__'
#         widgets = {
#             'items': JSONFormWidget(schema=PluginSchema),
#         }


# class PluginAdmin(admin.ModelAdmin):
#     formfield_overrides = {
#         PydanticSchemaField: {"widget": JSONFormWidget},
#     }
#     form = PluginForm

    
