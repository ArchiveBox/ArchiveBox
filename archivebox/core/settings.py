__package__ = 'archivebox.core'

import os
import sys
import re
import logging
import inspect
import tempfile
from typing import Any, Dict

from pathlib import Path
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

def find_plugins_in_dir(plugins_dir, prefix: str) -> Dict[str, Path]:
    return {
        f'{prefix}.{plugin_entrypoint.parent.name}': plugin_entrypoint.parent
        for plugin_entrypoint in sorted(plugins_dir.glob('*/apps.py'))
    }

INSTALLED_PLUGINS = {
    **find_plugins_in_dir(BUILTIN_PLUGINS_DIR, prefix='builtin_plugins'),
    **find_plugins_in_dir(USERDATA_PLUGINS_DIR, prefix='user_plugins'),
}

### Plugins Globals (filled by plugantic.apps.load_plugins() after Django startup)
PLUGINS = AttrDict({})
HOOKS = AttrDict({})

CONFIGS = AttrDict({})
BINPROVIDERS = AttrDict({})
BINARIES = AttrDict({})
EXTRACTORS = AttrDict({})
REPLAYERS = AttrDict({})
CHECKS = AttrDict({})
ADMINDATAVIEWS = AttrDict({})

PLUGIN_KEYS = AttrDict({
    'CONFIGS': CONFIGS,
    'BINPROVIDERS': BINPROVIDERS,
    'BINARIES': BINARIES,
    'EXTRACTORS': EXTRACTORS,
    'REPLAYERS': REPLAYERS,
    'CHECKS': CHECKS,
    'ADMINDATAVIEWS': ADMINDATAVIEWS,
})

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
    'django_jsonform',           # handles rendering Pydantic models to Django HTML widgets/forms
    'signal_webhooks',           # handles REST API outbound webhooks
    
    # our own apps
    'abid_utils',                # handles ABID ID creation, handling, and models
    'plugantic',                 # ArchiveBox plugin API definition + finding/registering/calling interface
    'core',                      # core django model with Snapshot, ArchiveResult, etc.
    'api',                       # Django-Ninja-based Rest API interfaces, config, APIToken model, etc.
    'pkg',                       # ArchiveBox runtime package management interface for subdependencies

    # ArchiveBox plugins
    *INSTALLED_PLUGINS.keys(),   # all plugin django-apps found in archivebox/builtin_plugins and data/user_plugins

    # 3rd-party apps from PyPI that need to be loaded last
    'admin_data_views',          # handles rendering some convenient automatic read-only views of data in Django admin
    'django_extensions',         # provides Django Debug Toolbar (and other non-debug helpers)
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

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATABASE_NAME,
        'OPTIONS': {
            'timeout': 60,
            'check_same_thread': False,
        },
        'TIME_ZONE': CONFIG.TIMEZONE,
        # DB setup is sometimes modified at runtime by setup_django() in config.py
    },
    # 'cache': {
    #     'ENGINE': 'django.db.backends.sqlite3',
    #     'NAME': CACHE_DB_PATH,
    #     'OPTIONS': {
    #         'timeout': 60,
    #         'check_same_thread': False,
    #     },
    #     'TIME_ZONE': CONFIG.TIMEZONE,
    # },
}
MIGRATION_MODULES = {'signal_webhooks': None}

# as much as I'd love this to be a UUID or ULID field, it's not supported yet as of Django 5.0
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


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

def add_extra_logging_attrs(record):
    record.username = ''
    try:
        record.username = record.request.user.username
    except AttributeError:
        record.username = "Anonymous"
        if hasattr(record, 'request'):
            import ipdb; ipdb.set_trace()
    return True


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
            "datefmt": "[%X]",
            # "format": "{asctime} {levelname} {module} {name} {message} {username}",
            # "format": "%(message)s  (user=%(username)s",
        },
        "verbose": {
            "style": "{",
        },
        "simple": {
            "format": "{name} {message}",
            "style": "{",
        },
        "django.server": {
            "()": "django.utils.log.ServerFormatter",
            # "format": "{message} (user={username})",
            "style": "{",
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
        # "add_extra_logging_attrs": {
        #     "()": "django.utils.log.CallbackFilter",
        #     "callback": add_extra_logging_attrs,
        # },
    },
    "handlers": {
        # "console": {
        #     "level": "DEBUG",
        #     'formatter': 'simple',
        #     "class": "logging.StreamHandler",
        #     'filters': ['noisyrequestsfilter', 'add_extra_logging_attrs'],
        # },
        "console": {
            "class": "rich.logging.RichHandler",
            "formatter": "rich",
            "level": "DEBUG",
            "markup": False,
            "rich_tracebacks": True,
            "filters": ["noisyrequestsfilter"],
            "tracebacks_suppress": [
                pydantic,
                django.template,
            ],
        },
        "logfile": {
            "level": "ERROR",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": ERROR_LOG,
            "maxBytes": 1024 * 1024 * 25,  # 25 MB
            "backupCount": 10,
            "formatter": "verbose",
            "filters": ["noisyrequestsfilter"],
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
        "handlers": ["console", "logfile"],
        "level": "INFO",
        "formatter": "verbose",
    },
    "loggers": {
        "api": {
            "handlers": ["console", "logfile"],
            "level": "DEBUG",
        },
        "checks": {
            "handlers": ["console", "logfile"],
            "level": "DEBUG",
        },
        "core": {
            "handlers": ["console", "logfile"],
            "level": "DEBUG",
        },
        "builtin_plugins": {
            "handlers": ["console", "logfile"],
            "level": "DEBUG",
        },
        "django": {
            "handlers": ["console", "logfile"],
            "level": "INFO",
            "filters": ["noisyrequestsfilter"],
        },
        "django.utils.autoreload": {
            "propagate": False,
            "handlers": [],
            "level": "ERROR",
        },
        "django.channels.server": {
            "propagate": False,
            "handlers": ["console", "logfile"],
            "level": "INFO",
            "filters": ["noisyrequestsfilter"],
            "formatter": "django.server",
        },
        "django.server": {  # logs all requests (2xx, 3xx, 4xx)
            "propagate": False,
            "handlers": ["console", "logfile"],
            "level": "INFO",
            "filters": ["noisyrequestsfilter"],
            "formatter": "django.server",
        },
        "django.request": {  # only logs 4xx and 5xx errors
            "propagate": False,
            "handlers": ["console", "logfile"],
            "level": "INFO",
            "filters": ["noisyrequestsfilter"],
            "formatter": "django.server",
        },
        "django.db.backends": {
            "propagate": False,
            "handlers": ["console"],
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
