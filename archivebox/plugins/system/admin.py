from django.contrib import admin
from solo.admin import SingletonModelAdmin

from plugins.defaults.admin import DependencyAdmin, ExtractorAdmin

from .models import (
	BashEnvironmentDependency,
	PythonEnvironmentDependency,
	NodeJSEnvironmentDependency,

	AptEnvironmentDependency,
	BrewEnvironmentDependency,
	PipEnvironmentDependency,
	NPMEnvironmentDependency,

	SQLiteDependency,
	DjangoDependency,
	ArchiveBoxDependency,

	# ArchiveBoxDefaultExtractor,
)


print('DefaultsPluginConfig.admin')

class MultiDependencyAdmin(admin.ModelAdmin):
	readonly_fields = DependencyAdmin.readonly_fields
	list_display = ('id', 'NAME', 'ENABLED', 'BINARY', 'ARGS', 'bin_path', 'bin_version', 'is_valid', 'is_enabled')

class MultiExtractorAdmin(admin.ModelAdmin):
	readonly_fields = DependencyAdmin.readonly_fields
	list_display = ('id', 'NAME', 'CMD', 'ARGS', 'is_valid', 'is_enabled')


# admin.site.register(BashEnvironmentDependency, DependencyAdmin)
admin.site.register(BashEnvironmentDependency, MultiDependencyAdmin)
admin.site.register(PythonEnvironmentDependency, DependencyAdmin)
admin.site.register(NodeJSEnvironmentDependency, DependencyAdmin)

admin.site.register(AptEnvironmentDependency, DependencyAdmin)
admin.site.register(BrewEnvironmentDependency, DependencyAdmin)
admin.site.register(PipEnvironmentDependency, DependencyAdmin)
admin.site.register(NPMEnvironmentDependency, DependencyAdmin)

admin.site.register(SQLiteDependency, DependencyAdmin)
admin.site.register(DjangoDependency, DependencyAdmin)
admin.site.register(ArchiveBoxDependency, DependencyAdmin)

# admin.site.register(ArchiveBoxDefaultExtractor, ExtractorAdmin)