from django.contrib import admin
from solo.admin import SingletonModelAdmin

from plugins.defaults.admin import DependencyAdmin, ExtractorAdmin

from .models import (
	BashEnvironmentDependency,
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


admin.site.register(BashEnvironmentDependency, DependencyAdmin)
admin.site.register(AptEnvironmentDependency, DependencyAdmin)
admin.site.register(BrewEnvironmentDependency, DependencyAdmin)
admin.site.register(PipEnvironmentDependency, DependencyAdmin)
admin.site.register(NPMEnvironmentDependency, DependencyAdmin)

admin.site.register(SQLiteDependency, DependencyAdmin)
admin.site.register(DjangoDependency, DependencyAdmin)
admin.site.register(ArchiveBoxDependency, DependencyAdmin)

# admin.site.register(ArchiveBoxDefaultExtractor, ExtractorAdmin)