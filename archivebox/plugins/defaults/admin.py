from django.contrib import admin
from solo.admin import SingletonModelAdmin

from .models import (
	ArchiveBoxDefaultDependency,
	ArchiveBoxDefaultExtractor,
)


class DependencyAdmin(SingletonModelAdmin):
	readonly_fields = ('REQUIRED', 'ENABLED', 'BINARY', 'ARGS', 'bin_path', 'bin_version', 'is_valid', 'is_enabled')

class ExtractorAdmin(SingletonModelAdmin):
	# readonly_fields = ('REQUIRED', 'ENABLED', 'BINARY', 'ARGS', 'bin_path', 'bin_version', 'is_valid', 'is_enabled')
	pass

print('DefaultsPluginConfig.admin')


admin.site.register(ArchiveBoxDefaultDependency, DependencyAdmin)
admin.site.register(ArchiveBoxDefaultExtractor, ExtractorAdmin)