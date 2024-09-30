__package__ = 'abx.django'

import itertools
# from benedict import benedict

from .. import pm


def get_INSTALLED_APPS():
    return itertools.chain(*reversed(pm.hook.get_INSTALLED_APPS()))

# def register_INSTALLLED_APPS(INSTALLED_APPS):
#     pm.hook.register_INSTALLED_APPS(INSTALLED_APPS=INSTALLED_APPS)


def get_MIDDLEWARES():
    return itertools.chain(*reversed(pm.hook.get_MIDDLEWARE()))

# def register_MIDDLEWARES(MIDDLEWARE):
#     pm.hook.register_MIDDLEWARE(MIDDLEWARE=MIDDLEWARE)


def get_AUTHENTICATION_BACKENDS():
    return itertools.chain(*reversed(pm.hook.get_AUTHENTICATION_BACKENDS()))

# def register_AUTHENTICATION_BACKENDS(AUTHENTICATION_BACKENDS):
#     pm.hook.register_AUTHENTICATION_BACKENDS(AUTHENTICATION_BACKENDS=AUTHENTICATION_BACKENDS)


def get_STATICFILES_DIRS():
    return itertools.chain(*reversed(pm.hook.get_STATICFILES_DIRS()))

# def register_STATICFILES_DIRS(STATICFILES_DIRS):
#     pm.hook.register_STATICFILES_DIRS(STATICFILES_DIRS=STATICFILES_DIRS)


def get_TEMPLATE_DIRS():
    return itertools.chain(*reversed(pm.hook.get_TEMPLATE_DIRS()))

# def register_TEMPLATE_DIRS(TEMPLATE_DIRS):
#     pm.hook.register_TEMPLATE_DIRS(TEMPLATE_DIRS=TEMPLATE_DIRS)

def get_DJANGO_HUEY_QUEUES(QUEUE_DATABASE_NAME='queue.sqlite3'):
    HUEY_QUEUES = {}
    for plugin_result in pm.hook.get_DJANGO_HUEY_QUEUES(QUEUE_DATABASE_NAME=QUEUE_DATABASE_NAME):
        HUEY_QUEUES.update(plugin_result)
    return HUEY_QUEUES

# def register_DJANGO_HUEY(DJANGO_HUEY):
#     pm.hook.register_DJANGO_HUEY(DJANGO_HUEY=DJANGO_HUEY)

def get_ADMIN_DATA_VIEWS_URLS():
    return itertools.chain(*reversed(pm.hook.get_ADMIN_DATA_VIEWS_URLS()))

# def register_ADMIN_DATA_VIEWS(ADMIN_DATA_VIEWS):
#     pm.hook.register_ADMIN_DATA_VIEWS(ADMIN_DATA_VIEWS=ADMIN_DATA_VIEWS)


# def register_settings(settings):
#     # convert settings dict to an benedict so we can set values using settings.attr = xyz notation
#     settings_as_obj = benedict(settings, keypath_separator=None)
    
#     # set default values for settings that are used by plugins
#     # settings_as_obj.INSTALLED_APPS = settings_as_obj.get('INSTALLED_APPS', [])
#     # settings_as_obj.MIDDLEWARE = settings_as_obj.get('MIDDLEWARE', [])
#     # settings_as_obj.AUTHENTICATION_BACKENDS = settings_as_obj.get('AUTHENTICATION_BACKENDS', [])
#     # settings_as_obj.STATICFILES_DIRS = settings_as_obj.get('STATICFILES_DIRS', [])
#     # settings_as_obj.TEMPLATE_DIRS = settings_as_obj.get('TEMPLATE_DIRS', [])
#     # settings_as_obj.DJANGO_HUEY = settings_as_obj.get('DJANGO_HUEY', {'queues': {}})
#     # settings_as_obj.ADMIN_DATA_VIEWS = settings_as_obj.get('ADMIN_DATA_VIEWS', {'URLS': []})
    
#     # # call all the hook functions to mutate the settings values in-place
#     # register_INSTALLLED_APPS(settings_as_obj.INSTALLED_APPS)
#     # register_MIDDLEWARES(settings_as_obj.MIDDLEWARE)
#     # register_AUTHENTICATION_BACKENDS(settings_as_obj.AUTHENTICATION_BACKENDS)
#     # register_STATICFILES_DIRS(settings_as_obj.STATICFILES_DIRS)
#     # register_TEMPLATE_DIRS(settings_as_obj.TEMPLATE_DIRS)
#     # register_DJANGO_HUEY(settings_as_obj.DJANGO_HUEY)
#     # register_ADMIN_DATA_VIEWS(settings_as_obj.ADMIN_DATA_VIEWS)
    
#     # calls Plugin.settings(settings) on each registered plugin
#     pm.hook.register_settings(settings=settings_as_obj)
    
#     # then finally update the settings globals() object will all the new settings
#     # settings.update(settings_as_obj)


def get_urlpatterns():
    return list(itertools.chain(*pm.hook.urlpatterns()))

def register_urlpatterns(urlpatterns):
    pm.hook.register_urlpatterns(urlpatterns=urlpatterns)


def register_checks():
    """register any django system checks"""
    pm.hook.register_checks()

