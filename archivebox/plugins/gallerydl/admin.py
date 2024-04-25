from django.contrib import admin
from solo.admin import SingletonModelAdmin

from .models import GalleryDLDependency, GalleryDLExtractor


admin.site.register(GalleryDLDependency, SingletonModelAdmin)
admin.site.register(GalleryDLExtractor, SingletonModelAdmin)