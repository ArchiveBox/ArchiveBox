from pathlib import Path

from django.conf import settings

def register_plugin_settings(settings=settings, name='defaults'):

	settings.STATICFILES_DIRS += [
		str(Path(settings.PACKAGE_DIR) / f'plugins/{name}/static'),
	]

	settings.TEMPLATE_DIRS += [
		str(Path(settings.PACKAGE_DIR) / f'plugins/{name}/templates'),
	]

	print('REGISTERED PLUGIN SETTINGS', name)