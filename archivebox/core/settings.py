__package__ = 'archivebox.core'

import os
import sys
import inspect

from pathlib import Path

from django.utils.crypto import get_random_string

import abx
import abx.archivebox
import abx.archivebox.use
import abx.django.use

from archivebox.config import DATA_DIR, PACKAGE_DIR, ARCHIVE_DIR, CONSTANTS
from archivebox.config.common import SHELL_CONFIG, SERVER_CONFIG      # noqa

IS_MIGRATING = 'makemigrations' in sys.argv[:3] or 'migrate' in sys.argv[:3]
IS_TESTING = 'test' in sys.argv[:3] or 'PYTEST_CURRENT_TEST' in os.environ
IS_SHELL = 'shell' in sys.argv[:3] or 'shell_plus' in sys.argv[:3]



################################################################################
### ArchiveBox Plugin Settings
################################################################################

PLUGIN_HOOKSPECS = [
    'abx.django.hookspec',
    'abx.pydantic_pkgr.hookspec',
    'abx.archivebox.hookspec',
]
abx.register_hookspecs(PLUGIN_HOOKSPECS)

BUILTIN_PLUGIN_DIRS = {
    'archivebox':              PACKAGE_DIR,
    'plugins_pkg':             PACKAGE_DIR / 'plugins_pkg',
    'plugins_auth':            PACKAGE_DIR / 'plugins_auth',
    'plugins_search':          PACKAGE_DIR / 'plugins_search',
    'plugins_extractor':       PACKAGE_DIR / 'plugins_extractor',
}
USER_PLUGIN_DIRS = {
    'user_plugins':            DATA_DIR / 'user_plugins',
}

# Discover ArchiveBox plugins
BUILTIN_PLUGINS = abx.get_plugins_in_dirs(BUILTIN_PLUGIN_DIRS)
PIP_PLUGINS = abx.get_pip_installed_plugins(group='archivebox')
USER_PLUGINS = abx.get_plugins_in_dirs(USER_PLUGIN_DIRS)
ALL_PLUGINS = {**BUILTIN_PLUGINS, **PIP_PLUGINS, **USER_PLUGINS}

# Load ArchiveBox plugins
PLUGIN_MANAGER = abx.pm
PLUGINS = abx.archivebox.load_archivebox_plugins(PLUGIN_MANAGER, ALL_PLUGINS)
HOOKS = abx.archivebox.use.get_HOOKS(PLUGINS)

# Load ArchiveBox config from plugins
CONFIGS = abx.archivebox.use.get_CONFIGS()
FLAT_CONFIG = abx.archivebox.use.get_FLAT_CONFIG()
BINPROVIDERS = abx.archivebox.use.get_BINPROVIDERS()
BINARIES = abx.archivebox.use.get_BINARIES()
EXTRACTORS = abx.archivebox.use.get_EXTRACTORS()
REPLAYERS = abx.archivebox.use.get_REPLAYERS()
CHECKS = abx.archivebox.use.get_CHECKS()
ADMINDATAVIEWS = abx.archivebox.use.get_ADMINDATAVIEWS()
QUEUES = abx.archivebox.use.get_QUEUES()
SEARCHBACKENDS = abx.archivebox.use.get_SEARCHBACKENDS()


################################################################################
### Django Core Settings
################################################################################

WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = "core.asgi.application"
ROOT_URLCONF = 'core.urls'

LOGIN_URL = '/accounts/login/'
LOGOUT_REDIRECT_URL = os.environ.get('LOGOUT_REDIRECT_URL', '/')

PASSWORD_RESET_URL = '/accounts/password_reset/'
APPEND_SLASH = True

DEBUG = SHELL_CONFIG.DEBUG or ('--debug' in sys.argv)


INSTALLED_APPS = [
    'daphne',

    # Django default apps
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',

    # 3rd-party apps from PyPI
    'django_jsonform',           # handles rendering Pydantic models to Django HTML widgets/forms  https://github.com/bhch/django-jsonform
    'signal_webhooks',           # handles REST API outbound webhooks                              https://github.com/MrThearMan/django-signal-webhooks
    'django_object_actions',     # provides easy Django Admin action buttons on change views       https://github.com/crccheck/django-object-actions

    # Our ArchiveBox-provided apps
    #'config',                   # ArchiveBox config settings (loaded as a plugin, don't need to add it here)
    'machine',                   # handles collecting and storing information about the host machine, network interfaces, installed binaries, etc.
    'queues',                    # handles starting and managing background workers and processes
    'abid_utils',                # handles ABID ID creation, handling, and models
    'core',                      # core django model with Snapshot, ArchiveResult, etc.
    'api',                       # Django-Ninja-based Rest API interfaces, config, APIToken model, etc.

    # ArchiveBox plugins
    *abx.django.use.get_INSTALLED_APPS(),  # all plugin django-apps found in archivebox/plugins_* and data/user_plugins,

    # 3rd-party apps from PyPI that need to be loaded last
    'admin_data_views',          # handles rendering some convenient automatic read-only views of data in Django admin
    'django_extensions',         # provides Django Debug Toolbar (and other non-debug helpers)
    'django_huey',               # provides multi-queue support for django huey https://github.com/gaiacoop/django-huey
    'bx_django_utils',           # needed for huey_monitor https://github.com/boxine/bx_django_utils
    'huey_monitor',              # adds an admin UI for monitoring background huey tasks https://github.com/boxine/django-huey-monitor

    # load plugins last so all other apps are already .ready() when we call plugins.ready()
    'abx',
]



MIDDLEWARE = [
    'core.middleware.TimezoneMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.ReverseProxyAuthMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'core.middleware.CacheControlMiddleware',
    *abx.django.use.get_MIDDLEWARES(),
]


################################################################################
### Authentication Settings
################################################################################

# AUTH_USER_MODEL = 'auth.User'   # cannot be easily changed unfortunately

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.RemoteUserBackend',
    'django.contrib.auth.backends.ModelBackend',
    *abx.django.use.get_AUTHENTICATION_BACKENDS(),
]


# from ..plugins_auth.ldap.settings import LDAP_CONFIG

# if LDAP_CONFIG.LDAP_ENABLED:
#     AUTH_LDAP_BIND_DN = LDAP_CONFIG.LDAP_BIND_DN
#     AUTH_LDAP_SERVER_URI = LDAP_CONFIG.LDAP_SERVER_URI
#     AUTH_LDAP_BIND_PASSWORD = LDAP_CONFIG.LDAP_BIND_PASSWORD
#     AUTH_LDAP_USER_ATTR_MAP = LDAP_CONFIG.LDAP_USER_ATTR_MAP
#     AUTH_LDAP_USER_SEARCH = LDAP_CONFIG.AUTH_LDAP_USER_SEARCH
    
#     AUTHENTICATION_BACKENDS = LDAP_CONFIG.AUTHENTICATION_BACKENDS

################################################################################
### Staticfile and Template Settings
################################################################################

STATIC_URL = '/static/'
TEMPLATES_DIR_NAME = 'templates'
CUSTOM_TEMPLATES_ENABLED = os.access(CONSTANTS.CUSTOM_TEMPLATES_DIR, os.R_OK) and CONSTANTS.CUSTOM_TEMPLATES_DIR.is_dir()
STATICFILES_DIRS = [
    *([str(CONSTANTS.CUSTOM_TEMPLATES_DIR / 'static')] if CUSTOM_TEMPLATES_ENABLED else []),
    # *[
    #     str(plugin_dir / 'static')
    #     for plugin_dir in PLUGIN_DIRS.values()
    #     if (plugin_dir / 'static').is_dir()
    # ],
    *abx.django.use.get_STATICFILES_DIRS(),
    str(PACKAGE_DIR / TEMPLATES_DIR_NAME / 'static'),
]

TEMPLATE_DIRS = [
    *([str(CONSTANTS.CUSTOM_TEMPLATES_DIR)] if CUSTOM_TEMPLATES_ENABLED else []),
    # *[
    #     str(plugin_dir / 'templates')
    #     for plugin_dir in PLUGIN_DIRS.values()
    #     if (plugin_dir / 'templates').is_dir()
    # ],
    *abx.django.use.get_TEMPLATE_DIRS(),
    str(PACKAGE_DIR / TEMPLATES_DIR_NAME / 'core'),
    str(PACKAGE_DIR / TEMPLATES_DIR_NAME / 'admin'),
    str(PACKAGE_DIR / TEMPLATES_DIR_NAME),
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': TEMPLATE_DIRS,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


################################################################################
### External Service Settings
################################################################################

# CACHE_DB_FILENAME = 'cache.sqlite3'
# CACHE_DB_PATH = CONSTANTS.CACHE_DIR / CACHE_DB_FILENAME
# CACHE_DB_TABLE = 'django_cache'

DATABASE_NAME = os.environ.get("ARCHIVEBOX_DATABASE_NAME", str(CONSTANTS.DATABASE_FILE))

SQLITE_CONNECTION_OPTIONS = {
    "ENGINE": "django.db.backends.sqlite3",
    "TIME_ZONE": CONSTANTS.TIMEZONE,
    "OPTIONS": {
        # https://gcollazo.com/optimal-sqlite-settings-for-django/
        # https://litestream.io/tips/#busy-timeout
        # https://docs.djangoproject.com/en/5.1/ref/databases/#setting-pragma-options
        "timeout": 5,
        "check_same_thread": False,
        "transaction_mode": "IMMEDIATE",
        "init_command": (
            "PRAGMA foreign_keys=ON;"
            "PRAGMA journal_mode = WAL;"
            "PRAGMA synchronous = NORMAL;"
            "PRAGMA temp_store = MEMORY;"
            "PRAGMA mmap_size = 134217728;"
            "PRAGMA journal_size_limit = 67108864;"
            "PRAGMA cache_size = 2000;"
        ),
    },
}

DATABASES = {
    "default": {
        "NAME": DATABASE_NAME,
        **SQLITE_CONNECTION_OPTIONS,
    },
    "queue": {
        "NAME": CONSTANTS.QUEUE_DATABASE_FILE,
        **SQLITE_CONNECTION_OPTIONS,
    },
    # 'cache': {
    #     'NAME': CACHE_DB_PATH,
    #     **SQLITE_CONNECTION_OPTIONS,
    # },
}
MIGRATION_MODULES = {'signal_webhooks': None}

# as much as I'd love this to be a UUID or ULID field, it's not supported yet as of Django 5.0
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


HUEY = {
    "huey_class": "huey.SqliteHuey",
    "filename": CONSTANTS.QUEUE_DATABASE_FILENAME,
    "name": "system_tasks",
    "results": True,
    "store_none": True,
    "immediate": False,
    "utc": True,
    "consumer": {
        "workers": 1,
        "worker_type": "thread",
        "initial_delay": 0.1,  # Smallest polling interval, same as -d.
        "backoff": 1.15,  # Exponential backoff using this rate, -b.
        "max_delay": 10.0,  # Max possible polling interval, -m.
        "scheduler_interval": 1,  # Check schedule every second, -s.
        "periodic": True,  # Enable crontab feature.
        "check_worker_health": True,  # Enable worker health checks.
        "health_check_interval": 1,  # Check worker health every second.
    },
}

# https://huey.readthedocs.io/en/latest/contrib.html#setting-things-up
# https://github.com/gaiacoop/django-huey
DJANGO_HUEY = {
    "default": "system_tasks",
    "queues": {
        HUEY["name"]: HUEY.copy(),
        # more registered here at plugin import-time by BaseQueue.register()
        **abx.django.use.get_DJANGO_HUEY_QUEUES(QUEUE_DATABASE_NAME=CONSTANTS.QUEUE_DATABASE_FILENAME),
    },
}

class HueyDBRouter:
    """
    A router to store all the Huey result k:v / Huey Monitor models in the queue.sqlite3 database.
    We keep the databases separate because the queue database receives many more reads/writes per second
    and we want to avoid single-write lock contention with the main database. Also all the in-progress task
    data is ephemeral/not-important-long-term. This makes it easier to for the user to clear non-critical
    temp data by just deleting queue.sqlite3 and leaving index.sqlite3.
    """

    route_app_labels = {"huey_monitor", "django_huey", "djhuey"}

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.route_app_labels:
            return "queue"
        return 'default'

    def db_for_write(self, model, **hints):
        if model._meta.app_label in self.route_app_labels:
            return "queue"
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._meta.app_label in self.route_app_labels or obj2._meta.app_label in self.route_app_labels:
            return obj1._meta.app_label == obj2._meta.app_label
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.route_app_labels:
            return db == "queue"
        return db == "default"

DATABASE_ROUTERS = ['core.settings.HueyDBRouter']

CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
    # 'sqlite': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'cache'},
    # 'dummy': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'},
    # 'filebased': {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache", "LOCATION": CACHE_DIR / 'cache_filebased'},
}

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
    "archive": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {
            "base_url": "/archive/",
            "location": ARCHIVE_DIR,
        },
    },
    # "personas": {
    #     "BACKEND": "django.core.files.storage.FileSystemStorage",
    #     "OPTIONS": {
    #         "base_url": "/personas/",
    #         "location": PERSONAS_DIR,
    #     },
    # },
}

################################################################################
### Security Settings
################################################################################

SECRET_KEY = SERVER_CONFIG.SECRET_KEY or get_random_string(50, 'abcdefghijklmnopqrstuvwxyz0123456789_')

ALLOWED_HOSTS = SERVER_CONFIG.ALLOWED_HOSTS.split(',')
CSRF_TRUSTED_ORIGINS = list(set(SERVER_CONFIG.CSRF_TRUSTED_ORIGINS.split(',')))

# automatically fix case when user sets ALLOWED_HOSTS (e.g. to archivebox.example.com)
# but forgets to add https://archivebox.example.com to CSRF_TRUSTED_ORIGINS
for hostname in ALLOWED_HOSTS:
    https_endpoint = f'https://{hostname}'
    if hostname != '*' and https_endpoint not in CSRF_TRUSTED_ORIGINS:
        print(f'[!] WARNING: {https_endpoint} from ALLOWED_HOSTS should be added to CSRF_TRUSTED_ORIGINS')
        CSRF_TRUSTED_ORIGINS.append(https_endpoint)

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_AGE = 1209600  # 2 weeks
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = False

SESSION_ENGINE = "django.contrib.sessions.backends.db"

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

DATA_UPLOAD_MAX_NUMBER_FIELDS = None
DATA_UPLOAD_MAX_MEMORY_SIZE = 26_214_400  # 25MB

################################################################################
### Shell Settings
################################################################################

SHELL_PLUS = 'ipython'
SHELL_PLUS_PRINT_SQL = False
IPYTHON_ARGUMENTS = ['--no-confirm-exit', '--no-banner']
IPYTHON_KERNEL_DISPLAY_NAME = 'ArchiveBox Django Shell'
if IS_SHELL:
    os.environ['PYTHONSTARTUP'] = str(PACKAGE_DIR / 'core' / 'shell_welcome_message.py')


################################################################################
### Internationalization & Localization Settings
################################################################################

LANGUAGE_CODE = 'en-us'
USE_I18N = True
USE_TZ = True
DATETIME_FORMAT = 'Y-m-d h:i:s A'
SHORT_DATETIME_FORMAT = 'Y-m-d h:i:s A'
TIME_ZONE = CONSTANTS.TIMEZONE        # django convention is TIME_ZONE, archivebox config uses TIMEZONE, they are equivalent


from django.conf.locale.en import formats as en_formats    # type: ignore

en_formats.DATETIME_FORMAT = DATETIME_FORMAT                # monkey patch en_format default with our preferred format
en_formats.SHORT_DATETIME_FORMAT = SHORT_DATETIME_FORMAT


################################################################################
### Logging Settings
################################################################################


from .settings_logging import SETTINGS_LOGGING, LOGS_DIR, ERROR_LOG

LOGGING = SETTINGS_LOGGING


################################################################################
### REST API Outbound Webhooks settings
################################################################################

# Add default webhook configuration to the User model
SIGNAL_WEBHOOKS_CUSTOM_MODEL = 'api.models.OutboundWebhook'
SIGNAL_WEBHOOKS = {
    "HOOKS": {
        # ... is a special sigil value that means "use the default autogenerated hooks"
        "django.contrib.auth.models.User": ...,
        "core.models.Snapshot": ...,
        "core.models.ArchiveResult": ...,
        "core.models.Tag": ...,
        "api.models.APIToken": ...,
    },
}

################################################################################
### Admin Data View Settings
################################################################################

ADMIN_DATA_VIEWS = {
    "NAME": "Environment",
    "URLS": [
        {
            "route": "config/",
            "view": "core.views.live_config_list_view",
            "name": "Configuration",
            "items": {
                "route": "<str:key>/",
                "view": "core.views.live_config_value_view",
                "name": "config_val",
            },
        },
        {
            "route": "binaries/",
            "view": "archivebox.config.views.binaries_list_view",
            "name": "Dependencies",
            "items": {
                "route": "<str:key>/",
                "view": "archivebox.config.views.binary_detail_view",
                "name": "binary",
            },
        },
        {
            "route": "plugins/",
            "view": "archivebox.config.views.plugins_list_view",
            "name": "Plugins",
            "items": {
                "route": "<str:key>/",
                "view": "archivebox.config.views.plugin_detail_view",
                "name": "plugin",
            },
        },
        {
            "route": "workers/",
            "view": "archivebox.config.views.worker_list_view",
            "name": "Workers",
            "items": {
                "route": "<str:key>/",
                "view": "archivebox.config.views.worker_detail_view",
                "name": "worker",
            },
        },
        {
            "route": "logs/",
            "view": "archivebox.config.views.log_list_view",
            "name": "Logs",
            "items": {
                "route": "<str:key>/",
                "view": "archivebox.config.views.log_detail_view",
                "name": "log",
            },
        },
        *abx.django.use.get_ADMIN_DATA_VIEWS_URLS(),
    ],
}


################################################################################
### Debug Settings
################################################################################

# only enable debug toolbar when in DEBUG mode with --nothreading (it doesnt work in multithreaded mode)
DEBUG_TOOLBAR = False
DEBUG_TOOLBAR = DEBUG_TOOLBAR and DEBUG and ('--nothreading' in sys.argv) and ('--reload' not in sys.argv)
if DEBUG_TOOLBAR:
    try:
        import debug_toolbar   # noqa
        DEBUG_TOOLBAR = True
    except ImportError:
        DEBUG_TOOLBAR = False

if DEBUG_TOOLBAR:
    INSTALLED_APPS = [*INSTALLED_APPS, 'debug_toolbar']
    INTERNAL_IPS = ['0.0.0.0', '127.0.0.1', '*']
    DEBUG_TOOLBAR_CONFIG = {
        "SHOW_TOOLBAR_CALLBACK": lambda request: True,
        "RENDER_PANELS": True,
    }
    DEBUG_TOOLBAR_PANELS = [
        'debug_toolbar.panels.history.HistoryPanel',
        'debug_toolbar.panels.versions.VersionsPanel',
        'debug_toolbar.panels.timer.TimerPanel',
        'debug_toolbar.panels.settings.SettingsPanel',
        'debug_toolbar.panels.headers.HeadersPanel',
        'debug_toolbar.panels.request.RequestPanel',
        'debug_toolbar.panels.sql.SQLPanel',
        'debug_toolbar.panels.staticfiles.StaticFilesPanel',
        # 'debug_toolbar.panels.templates.TemplatesPanel',
        'debug_toolbar.panels.cache.CachePanel',
        'debug_toolbar.panels.signals.SignalsPanel',
        'debug_toolbar.panels.logging.LoggingPanel',
        'debug_toolbar.panels.redirects.RedirectsPanel',
        'debug_toolbar.panels.profiling.ProfilingPanel',
        'djdt_flamegraph.FlamegraphPanel',
    ]
    MIDDLEWARE = [*MIDDLEWARE, 'debug_toolbar.middleware.DebugToolbarMiddleware']

if DEBUG:
    from django_autotyping.typing import AutotypingSettingsDict

    INSTALLED_APPS += ['django_autotyping']
    AUTOTYPING: AutotypingSettingsDict = {
        "STUBS_GENERATION": {
            "LOCAL_STUBS_DIR": PACKAGE_DIR / "typings",
        }
    }

# https://github.com/bensi94/Django-Requests-Tracker (improved version of django-debug-toolbar)
# Must delete archivebox/templates/admin to use because it relies on some things we override
# visit /__requests_tracker__/ to access
DEBUG_REQUESTS_TRACKER = True
DEBUG_REQUESTS_TRACKER = DEBUG_REQUESTS_TRACKER and DEBUG
if DEBUG_REQUESTS_TRACKER:
    import requests_tracker

    INSTALLED_APPS += ["requests_tracker"]
    MIDDLEWARE += ["requests_tracker.middleware.requests_tracker_middleware"]
    INTERNAL_IPS = ["127.0.0.1", "10.0.2.2", "0.0.0.0", "*"]

    TEMPLATE_DIRS.insert(0, str(Path(inspect.getfile(requests_tracker)).parent / "templates"))

    REQUESTS_TRACKER_CONFIG = {
        "TRACK_SQL": True,
        "ENABLE_STACKTRACES": False,
        "IGNORE_PATHS_PATTERNS": (
            r".*/favicon\.ico",
            r".*\.png",
            r"/admin/jsi18n/",
        ),
        "IGNORE_SQL_PATTERNS": (
            r"^SELECT .* FROM django_migrations WHERE app = 'requests_tracker'",
            r"^SELECT .* FROM django_migrations WHERE app = 'auth'",
        ),
    }

# # https://docs.pydantic.dev/logfire/integrations/django/ (similar to DataDog / NewRelic / etc.)
# DEBUG_LOGFIRE = False
# DEBUG_LOGFIRE = DEBUG_LOGFIRE and os.access(DATA_DIR / '.logfire', os.W_OK) and (DATA_DIR / '.logfire').is_dir()


# For usage with https://www.jetadmin.io/integrations/django
# INSTALLED_APPS += ['jet_django']
# JET_PROJECT = 'archivebox'
# JET_TOKEN = 'some-api-token-here'


abx.django.use.register_checks()
abx.archivebox.use.register_all_hooks(globals())

# import ipdb; ipdb.set_trace()
