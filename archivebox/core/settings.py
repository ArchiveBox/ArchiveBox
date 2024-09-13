__package__ = 'archivebox.core'

import os
import sys
import re
import logging
import inspect
import tempfile

from typing import Dict
from pathlib import Path

import django
from django.utils.crypto import get_random_string

from ..config import CONFIG
from ..config_stubs import AttrDict
assert isinstance(CONFIG, AttrDict)

IS_MIGRATING = 'makemigrations' in sys.argv[:3] or 'migrate' in sys.argv[:3]
IS_TESTING = 'test' in sys.argv[:3] or 'PYTEST_CURRENT_TEST' in os.environ
IS_SHELL = 'shell' in sys.argv[:3] or 'shell_plus' in sys.argv[:3]


################################################################################
### ArchiveBox Plugin Settings
################################################################################

BUILTIN_PLUGINS_DIR = CONFIG.PACKAGE_DIR / 'builtin_plugins'  # /app/archivebox/builtin_plugins
USERDATA_PLUGINS_DIR = CONFIG.OUTPUT_DIR / 'user_plugins'     # /data/user_plugins

# PLUGIN_IMPORT_ORDER = ['base', 'pip', 'npm', 'ytdlp']
#
# def get_plugin_order(p: Path) -> str:
#     return str(PLUGIN_IMPORT_ORDER.index(p.parent.name)) if p.parent.name in PLUGIN_IMPORT_ORDER else str(p)

def find_plugins_in_dir(plugins_dir: Path, prefix: str) -> Dict[str, Path]:
    """{"builtin_plugins.pip": "/app/archivebox/builtin_plugins/pip", "user_plugins.other": "/data/user_plugins/other",...}"""
    return {
        f"{prefix}.{plugin_entrypoint.parent.name}": plugin_entrypoint.parent
        for plugin_entrypoint in sorted(plugins_dir.glob("*/apps.py"))   # key=get_plugin_order  # Someday enforcing plugin import order may be required, but right now it's not needed
    }

INSTALLED_PLUGINS = {
    **find_plugins_in_dir(BUILTIN_PLUGINS_DIR, prefix='builtin_plugins'),
    **find_plugins_in_dir(USERDATA_PLUGINS_DIR, prefix='user_plugins'),
}

### Plugins Globals (filled by builtin_plugins.npm.apps.NpmPlugin.register() after Django startup)
PLUGINS = AttrDict({})
HOOKS = AttrDict({})

# Created later by Hook.register(settings) when each Plugin.register(settings) is called
# CONFIGS = AttrDict({})
# BINPROVIDERS = AttrDict({})
# BINARIES = AttrDict({})
# EXTRACTORS = AttrDict({})
# REPLAYERS = AttrDict({})
# CHECKS = AttrDict({})
# ADMINDATAVIEWS = AttrDict({})


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

DEBUG = CONFIG.DEBUG or ('--debug' in sys.argv)


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
    'queues',                    # handles starting and managing background workers and processes
    'abid_utils',                # handles ABID ID creation, handling, and models
    'plugantic',                 # ArchiveBox plugin API definition + finding/registering/calling interface
    'core',                      # core django model with Snapshot, ArchiveResult, etc.
    'api',                       # Django-Ninja-based Rest API interfaces, config, APIToken model, etc.

    # ArchiveBox plugins
    *INSTALLED_PLUGINS.keys(),   # all plugin django-apps found in archivebox/builtin_plugins and data/user_plugins,
    # plugin.register(settings) is called at import of each plugin (in the order they are listed here), then plugin.ready() is called at AppConfig.ready() time

    # 3rd-party apps from PyPI that need to be loaded last
    'admin_data_views',          # handles rendering some convenient automatic read-only views of data in Django admin
    'django_extensions',         # provides Django Debug Toolbar (and other non-debug helpers)
    'django_huey',               # provides multi-queue support for django huey https://github.com/gaiacoop/django-huey
    'bx_django_utils',           # needed for huey_monitor https://github.com/boxine/bx_django_utils
    'huey_monitor',              # adds an admin UI for monitoring background huey tasks https://github.com/boxine/django-huey-monitor
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
]

################################################################################
### Authentication Settings
################################################################################

# AUTH_USER_MODEL = 'auth.User'   # cannot be easily changed unfortunately

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.RemoteUserBackend',
    'django.contrib.auth.backends.ModelBackend',
]

if CONFIG.LDAP:
    try:
        import ldap
        from django_auth_ldap.config import LDAPSearch

        global AUTH_LDAP_SERVER_URI
        global AUTH_LDAP_BIND_DN
        global AUTH_LDAP_BIND_PASSWORD
        global AUTH_LDAP_USER_SEARCH
        global AUTH_LDAP_USER_ATTR_MAP

        AUTH_LDAP_SERVER_URI = CONFIG.LDAP_SERVER_URI
        AUTH_LDAP_BIND_DN = CONFIG.LDAP_BIND_DN
        AUTH_LDAP_BIND_PASSWORD = CONFIG.LDAP_BIND_PASSWORD

        assert AUTH_LDAP_SERVER_URI and CONFIG.LDAP_USERNAME_ATTR and CONFIG.LDAP_USER_FILTER, 'LDAP_* config options must all be set if LDAP=True'

        AUTH_LDAP_USER_SEARCH = LDAPSearch(
            CONFIG.LDAP_USER_BASE,
            ldap.SCOPE_SUBTREE,
            '(&(' + CONFIG.LDAP_USERNAME_ATTR + '=%(user)s)' + CONFIG.LDAP_USER_FILTER + ')',
        )

        AUTH_LDAP_USER_ATTR_MAP = {
            'username': CONFIG.LDAP_USERNAME_ATTR,
            'first_name': CONFIG.LDAP_FIRSTNAME_ATTR,
            'last_name': CONFIG.LDAP_LASTNAME_ATTR,
            'email': CONFIG.LDAP_EMAIL_ATTR,
        }

        AUTHENTICATION_BACKENDS = [
            'django.contrib.auth.backends.ModelBackend',
            'django_auth_ldap.backend.LDAPBackend',
        ]
    except ModuleNotFoundError:
        sys.stderr.write('[X] Error: Found LDAP=True config but LDAP packages not installed. You may need to run: pip install archivebox[ldap]\n\n')
        # dont hard exit here. in case the user is just running "archivebox version" or "archivebox help", we still want those to work despite broken ldap
        # sys.exit(1)



################################################################################
### Staticfile and Template Settings
################################################################################

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    *([str(CONFIG.CUSTOM_TEMPLATES_DIR / 'static')] if CONFIG.CUSTOM_TEMPLATES_DIR else []),
    str(Path(CONFIG.PACKAGE_DIR) / CONFIG.TEMPLATES_DIR_NAME / 'static'),
]

TEMPLATE_DIRS = [
    *([str(CONFIG.CUSTOM_TEMPLATES_DIR)] if CONFIG.CUSTOM_TEMPLATES_DIR else []),
    str(Path(CONFIG.PACKAGE_DIR) / CONFIG.TEMPLATES_DIR_NAME / 'core'),
    str(Path(CONFIG.PACKAGE_DIR) / CONFIG.TEMPLATES_DIR_NAME / 'admin'),
    str(Path(CONFIG.PACKAGE_DIR) / CONFIG.TEMPLATES_DIR_NAME),
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


CACHE_DB_FILENAME = 'cache.sqlite3'
CACHE_DB_PATH = CONFIG.CACHE_DIR / CACHE_DB_FILENAME
CACHE_DB_TABLE = 'django_cache'

DATABASE_FILE = Path(CONFIG.OUTPUT_DIR) / CONFIG.SQL_INDEX_FILENAME
DATABASE_NAME = os.environ.get("ARCHIVEBOX_DATABASE_NAME", str(DATABASE_FILE))

QUEUE_DATABASE_NAME = DATABASE_NAME.replace('index.sqlite3', 'queue.sqlite3')

SQLITE_CONNECTION_OPTIONS = {
    "TIME_ZONE": CONFIG.TIMEZONE,
    "OPTIONS": {
        # https://gcollazo.com/optimal-sqlite-settings-for-django/
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
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATABASE_NAME,
        # DB setup is sometimes modified at runtime by setup_django() in config.py
    },
    "queue": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": QUEUE_DATABASE_NAME,
        **SQLITE_CONNECTION_OPTIONS,
    },
    # 'cache': {
    #     'ENGINE': 'django.db.backends.sqlite3',
    #     'NAME': CACHE_DB_PATH,
    #     **SQLITE_CONNECTION_OPTIONS,
    # },
}
MIGRATION_MODULES = {'signal_webhooks': None}

# as much as I'd love this to be a UUID or ULID field, it's not supported yet as of Django 5.0
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


HUEY = {
    "huey_class": "huey.SqliteHuey",
    "filename": QUEUE_DATABASE_NAME,
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
            "location": CONFIG.ARCHIVE_DIR,
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

SECRET_KEY = CONFIG.SECRET_KEY or get_random_string(50, 'abcdefghijklmnopqrstuvwxyz0123456789_')

ALLOWED_HOSTS = CONFIG.ALLOWED_HOSTS.split(',')
CSRF_TRUSTED_ORIGINS = list(set(CONFIG.CSRF_TRUSTED_ORIGINS.split(',')))

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
    os.environ['PYTHONSTARTUP'] = str(Path(CONFIG.PACKAGE_DIR) / 'core' / 'welcome_message.py')


################################################################################
### Internationalization & Localization Settings
################################################################################

LANGUAGE_CODE = 'en-us'
USE_I18N = True
USE_TZ = True
DATETIME_FORMAT = 'Y-m-d h:i:s A'
SHORT_DATETIME_FORMAT = 'Y-m-d h:i:s A'
TIME_ZONE = CONFIG.TIMEZONE        # django convention is TIME_ZONE, archivebox config uses TIMEZONE, they are equivalent


from django.conf.locale.en import formats as en_formats    # type: ignore

en_formats.DATETIME_FORMAT = DATETIME_FORMAT
en_formats.SHORT_DATETIME_FORMAT = SHORT_DATETIME_FORMAT


################################################################################
### Logging Settings
################################################################################

IGNORABLE_URL_PATTERNS = [
    re.compile(r"/.*/?apple-touch-icon.*\.png"),
    re.compile(r"/.*/?favicon\.ico"),
    re.compile(r"/.*/?robots\.txt"),
    re.compile(r"/.*/?.*\.(css|js)\.map"),
    re.compile(r"/.*/?.*\.(css|js)\.map"),
    re.compile(r"/static/.*"),
    re.compile(r"/admin/jsi18n/"),
]

class NoisyRequestsFilter(logging.Filter):
    def filter(self, record) -> bool:
        logline = record.getMessage()
        # '"GET /api/v1/docs HTTP/1.1" 200 1023'
        # '"GET /static/admin/js/SelectFilter2.js HTTP/1.1" 200 15502'
        # '"GET /static/admin/js/SelectBox.js HTTP/1.1" 304 0'
        # '"GET /admin/jsi18n/ HTTP/1.1" 200 3352'
        # '"GET /admin/api/apitoken/0191bbf8-fd5e-0b8c-83a8-0f32f048a0af/change/ HTTP/1.1" 200 28778'

        # ignore harmless 404s for the patterns in IGNORABLE_URL_PATTERNS
        for pattern in IGNORABLE_URL_PATTERNS:
            ignorable_GET_request = re.compile(f'"GET {pattern.pattern} HTTP/.*" (2..|30.|404) .+$', re.I | re.M)
            if ignorable_GET_request.match(logline):
                return False

            ignorable_404_pattern = re.compile(f'Not Found: {pattern.pattern}', re.I | re.M)
            if ignorable_404_pattern.match(logline):
                return False

        return True


class CustomOutboundWebhookLogFormatter(logging.Formatter):
    def format(self, record):
        result = super().format(record)
        return result.replace('HTTP Request: ', 'OutboundWebhook: ')


ERROR_LOG = tempfile.NamedTemporaryFile().name

if CONFIG.LOGS_DIR.exists():
    ERROR_LOG = (CONFIG.LOGS_DIR / 'errors.log')
else:
    # historically too many edge cases here around creating log dir w/ correct permissions early on
    # if there's an issue on startup, we trash the log and let user figure it out via stdout/stderr
    print(f'[!] WARNING: data/logs dir does not exist. Logging to temp file: {ERROR_LOG}')


LOG_LEVEL_DATABASE = 'DEBUG' if DEBUG else 'WARNING'
LOG_LEVEL_REQUEST = 'DEBUG' if DEBUG else 'WARNING'

import pydantic
import django.template

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "rich": {
            "datefmt": "[%Y-%m-%d %H:%M:%S]",
            # "format": "{asctime} {levelname} {module} {name} {message} {username}",
            "format": "%(name)s %(message)s",
        },
        "outbound_webhooks": {
            "()": CustomOutboundWebhookLogFormatter,
            "datefmt": "[%Y-%m-%d %H:%M:%S]",
        },
    },
    "filters": {
        "noisyrequestsfilter": {
            "()": NoisyRequestsFilter,
        },
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    "handlers": {
        # "console": {
        #     "level": "DEBUG",
        #     'formatter': 'simple',
        #     "class": "logging.StreamHandler",
        #     'filters': ['noisyrequestsfilter', 'add_extra_logging_attrs'],
        # },
        "default": {
            "class": "rich.logging.RichHandler",
            "formatter": "rich",
            "level": "DEBUG",
            "markup": False,
            "rich_tracebacks": True,
            "filters": ["noisyrequestsfilter"],
            "tracebacks_suppress": [
                django,
                pydantic,
            ],
        },
        "logfile": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": ERROR_LOG,
            "maxBytes": 1024 * 1024 * 25,  # 25 MB
            "backupCount": 10,
            "formatter": "rich",
            "filters": ["noisyrequestsfilter"],
        },
        "outbound_webhooks": {
            "class": "rich.logging.RichHandler",
            "markup": False,
            "rich_tracebacks": True,
            "formatter": "outbound_webhooks",
        },
        # "mail_admins": {
        #     "level": "ERROR",
        #     "filters": ["require_debug_false"],
        #     "class": "django.utils.log.AdminEmailHandler",
        # },
        "null": {
            "class": "logging.NullHandler",
        },
    },
    "root": {
        "handlers": ["default", "logfile"],
        "level": "INFO",
        "formatter": "rich",
    },
    "loggers": {
        "api": {
            "handlers": ["default", "logfile"],
            "level": "DEBUG",
        },
        "checks": {
            "handlers": ["default", "logfile"],
            "level": "DEBUG",
        },
        "core": {
            "handlers": ["default", "logfile"],
            "level": "DEBUG",
        },
        "builtin_plugins": {
            "handlers": ["default", "logfile"],
            "level": "DEBUG",
        },
        "httpx": {
            "handlers": ["outbound_webhooks"],
            "level": "INFO",
            "formatter": "outbound_webhooks",
            "propagate": False,
        },
        "django": {
            "handlers": ["default", "logfile"],
            "level": "INFO",
            "filters": ["noisyrequestsfilter"],
        },
        "django.utils.autoreload": {
            "propagate": False,
            "handlers": [],
            "level": "ERROR",
        },
        "django.channels.server": {
            # see archivebox.monkey_patches.ModifiedAccessLogGenerator for dedicated daphne server logging settings
            "propagate": False,
            "handlers": ["default", "logfile"],
            "level": "INFO",
            "filters": ["noisyrequestsfilter"],
        },
        "django.server": {  # logs all requests (2xx, 3xx, 4xx)
            "propagate": False,
            "handlers": ["default", "logfile"],
            "level": "INFO",
            "filters": ["noisyrequestsfilter"],
        },
        "django.request": {  # only logs 4xx and 5xx errors
            "propagate": False,
            "handlers": ["default", "logfile"],
            "level": "ERROR",
            "filters": ["noisyrequestsfilter"],
        },
        "django.db.backends": {
            "propagate": False,
            "handlers": ["default"],
            "level": LOG_LEVEL_DATABASE,
        },
    },
}


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
            "view": "plugantic.views.binaries_list_view",
            "name": "Binaries",
            "items": {
                "route": "<str:key>/",
                "view": "plugantic.views.binary_detail_view",
                "name": "binary",
            },
        },
        {
            "route": "plugins/",
            "view": "plugantic.views.plugins_list_view",
            "name": "Plugins",
            "items": {
                "route": "<str:key>/",
                "view": "plugantic.views.plugin_detail_view",
                "name": "plugin",
            },
        },
        {
            "route": "workers/",
            "view": "plugantic.views.worker_list_view",
            "name": "Workers",
            "items": {
                "route": "<str:key>/",
                "view": "plugantic.views.worker_detail_view",
                "name": "worker",
            },
        },
        {
            "route": "logs/",
            "view": "plugantic.views.log_list_view",
            "name": "Logs",
            "items": {
                "route": "<str:key>/",
                "view": "plugantic.views.log_detail_view",
                "name": "log",
            },
        },
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
            "LOCAL_STUBS_DIR": Path(CONFIG.PACKAGE_DIR) / "typings",
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

# https://docs.pydantic.dev/logfire/integrations/django/ (similar to DataDog / NewRelic / etc.)
DEBUG_LOGFIRE = False
DEBUG_LOGFIRE = DEBUG_LOGFIRE and (Path(CONFIG.OUTPUT_DIR) / '.logfire').is_dir()


# For usage with https://www.jetadmin.io/integrations/django
# INSTALLED_APPS += ['jet_django']
# JET_PROJECT = 'archivebox'
# JET_TOKEN = 'some-api-token-here'
