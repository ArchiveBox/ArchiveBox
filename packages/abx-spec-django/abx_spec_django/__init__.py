import abx

###########################################################################################

@abx.hookspec
@abx.hookimpl
def get_INSTALLED_APPS():
    """Return a list of apps to add to INSTALLED_APPS"""
    # e.g. ['your_plugin_type.plugin_name']
    return ['abx_spec_django']

# @abx.hookspec
# @abx.hookimpl
# def register_INSTALLED_APPS(INSTALLED_APPS):
#     """Mutate INSTALLED_APPS in place to add your app in a specific position"""
#     # idx_of_contrib = INSTALLED_APPS.index('django.contrib.auth')
#     # INSTALLED_APPS.insert(idx_of_contrib + 1, 'your_plugin_type.plugin_name')
#     pass


@abx.hookspec
@abx.hookimpl
def get_TEMPLATE_DIRS():
    return []     # e.g. ['your_plugin_type/plugin_name/templates']

# @abx.hookspec
# @abx.hookimpl
# def register_TEMPLATE_DIRS(TEMPLATE_DIRS):
#     """Install django settings"""
#     # e.g. TEMPLATE_DIRS.insert(0, 'your_plugin_type/plugin_name/templates')
#     pass


@abx.hookspec
@abx.hookimpl
def get_STATICFILES_DIRS():
    return []     # e.g. ['your_plugin_type/plugin_name/static']

# @abx.hookspec
# @abx.hookimpl
# def register_STATICFILES_DIRS(STATICFILES_DIRS):
#     """Mutate STATICFILES_DIRS in place to add your static dirs in a specific position"""
#     # e.g. STATICFILES_DIRS.insert(0, 'your_plugin_type/plugin_name/static')
#     pass


@abx.hookspec
@abx.hookimpl
def get_MIDDLEWARES():
    return []     # e.g. ['your_plugin_type.plugin_name.middleware.YourMiddleware']

# @abx.hookspec
# @abx.hookimpl
# def register_MIDDLEWARE(MIDDLEWARE):
#     """Mutate MIDDLEWARE in place to add your middleware in a specific position"""
#     # e.g. MIDDLEWARE.insert(0, 'your_plugin_type.plugin_name.middleware.YourMiddleware')
#     pass


@abx.hookspec
@abx.hookimpl
def get_AUTHENTICATION_BACKENDS():
    return []     # e.g. ['django_auth_ldap.backend.LDAPBackend']

# @abx.hookspec
# @abx.hookimpl
# def register_AUTHENTICATION_BACKENDS(AUTHENTICATION_BACKENDS):
#     """Mutate AUTHENTICATION_BACKENDS in place to add your auth backends in a specific position"""
#     # e.g. AUTHENTICATION_BACKENDS.insert(0, 'your_plugin_type.plugin_name.backend.YourBackend')
#     pass

@abx.hookspec
@abx.hookimpl
def get_DJANGO_HUEY_QUEUES(QUEUE_DATABASE_NAME):
    return {}     # e.g. {'some_queue_name': {'filename': 'some_queue_name.sqlite3', 'store_none': True, 'results': True, ...}}

# @abx.hookspec
# @abx.hookimpl
# def register_DJANGO_HUEY(DJANGO_HUEY):
#     """Mutate DJANGO_HUEY in place to add your huey queues in a specific position"""
#     # e.g. DJANGO_HUEY['queues']['some_queue_name']['some_setting'] = 'some_value'
#     pass


@abx.hookspec
@abx.hookimpl
def get_ADMIN_DATA_VIEWS_URLS():
    return []

# @abx.hookspec
# @abx.hookimpl
# def register_ADMIN_DATA_VIEWS(ADMIN_DATA_VIEWS):
#     """Mutate ADMIN_DATA_VIEWS in place to add your admin data views in a specific position"""
#     # e.g. ADMIN_DATA_VIEWS['URLS'].insert(0, 'your_plugin_type/plugin_name/admin_data_views.py')
#     pass


# @abx.hookspec
# @abx.hookimpl
# def register_settings(settings):
#     """Mutate settings in place to add your settings / modify existing settings"""
#     # settings.SOME_KEY = 'some_value'
#     pass


###########################################################################################

@abx.hookspec
@abx.hookimpl
def get_urlpatterns():
    return []     # e.g. [path('your_plugin_type/plugin_name/url.py', your_view)]

# @abx.hookspec
# @abx.hookimpl
# def register_urlpatterns(urlpatterns):
#     """Mutate urlpatterns in place to add your urlpatterns in a specific position"""
#     # e.g. urlpatterns.insert(0, path('your_plugin_type/plugin_name/url.py', your_view))
#     pass

###########################################################################################



@abx.hookspec
@abx.hookimpl
def register_admin(admin_site):
    """Register django admin views/models with the main django admin site instance"""
    # e.g. admin_site.register(your_model, your_admin_class)
    pass


###########################################################################################


@abx.hookspec
@abx.hookimpl
def ready():
    """Called when Django apps app.ready() are triggered"""
    # e.g. abx.pm.hook.get_CONFIG().ytdlp.validate()
    pass
