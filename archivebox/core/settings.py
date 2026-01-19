__package__ = "archivebox.core"

import os
import sys
import inspect

from pathlib import Path

from django.utils.crypto import get_random_string

import archivebox

from archivebox.config import DATA_DIR, PACKAGE_DIR, ARCHIVE_DIR, CONSTANTS  # noqa
from archivebox.config.common import SHELL_CONFIG, SERVER_CONFIG, STORAGE_CONFIG  # noqa


IS_MIGRATING = "makemigrations" in sys.argv[:3] or "migrate" in sys.argv[:3]
IS_TESTING = "test" in sys.argv[:3] or "PYTEST_CURRENT_TEST" in os.environ
IS_SHELL = "shell" in sys.argv[:3] or "shell_plus" in sys.argv[:3]
IS_GETTING_VERSION_OR_HELP = "version" in sys.argv or "help" in sys.argv or "--version" in sys.argv or "--help" in sys.argv

################################################################################
### ArchiveBox Plugin Settings
################################################################################

ALL_PLUGINS = archivebox.ALL_PLUGINS
LOADED_PLUGINS = archivebox.LOADED_PLUGINS

################################################################################
### Django Core Settings
################################################################################

WSGI_APPLICATION = "archivebox.core.wsgi.application"
ASGI_APPLICATION = "archivebox.core.asgi.application"
ROOT_URLCONF = "archivebox.core.urls"

LOGIN_URL = "/accounts/login/"
LOGOUT_REDIRECT_URL = os.environ.get("LOGOUT_REDIRECT_URL", "/")

PASSWORD_RESET_URL = "/accounts/password_reset/"
APPEND_SLASH = True

DEBUG = SHELL_CONFIG.DEBUG or ("--debug" in sys.argv)


INSTALLED_APPS = [
    "daphne",
    # Django default apps
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    # 3rd-party apps from PyPI
    "signal_webhooks",  # handles REST API outbound webhooks                              https://github.com/MrThearMan/django-signal-webhooks
    "django_object_actions",  # provides easy Django Admin action buttons on change views       https://github.com/crccheck/django-object-actions
    # Our ArchiveBox-provided apps (use fully qualified names)
    # NOTE: Order matters! Apps with migrations that depend on other apps must come AFTER their dependencies
    # "archivebox.config",  # ArchiveBox config settings (no models, not a real Django app)
    "archivebox.machine",  # handles collecting and storing information about the host machine, network interfaces, binaries, etc.
    "archivebox.workers",  # handles starting and managing background workers and processes (orchestrators and actors)
    "archivebox.personas",  # handles Persona and session management
    "archivebox.core",  # core django model with Snapshot, ArchiveResult, etc. (crawls depends on this)
    "archivebox.crawls",  # handles Crawl and CrawlSchedule models and management (depends on core)
    "archivebox.api",  # Django-Ninja-based Rest API interfaces, config, APIToken model, etc.
    # ArchiveBox plugins (hook-based plugins no longer add Django apps)
    # Use hooks.py discover_hooks() for plugin functionality
    # 3rd-party apps from PyPI that need to be loaded last
    "admin_data_views",  # handles rendering some convenient automatic read-only views of data in Django admin
    "django_extensions",  # provides Django Debug Toolbar (and other non-debug helpers)
]


MIDDLEWARE = [
    "archivebox.core.middleware.TimezoneMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "archivebox.core.middleware.ReverseProxyAuthMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "archivebox.core.middleware.CacheControlMiddleware",
    # Additional middlewares from plugins (if any)
]


################################################################################
### Authentication Settings
################################################################################

# AUTH_USER_MODEL = 'auth.User'   # cannot be easily changed unfortunately

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.RemoteUserBackend",
    "django.contrib.auth.backends.ModelBackend",
    # Additional auth backends (e.g., LDAP) configured via settings
]


# LDAP Authentication Configuration
# Conditionally loaded if LDAP_ENABLED=True and django-auth-ldap is installed
try:
    from archivebox.config.ldap import LDAP_CONFIG

    if LDAP_CONFIG.LDAP_ENABLED:
        # Validate LDAP configuration
        is_valid, error_msg = LDAP_CONFIG.validate_ldap_config()
        if not is_valid:
            from rich import print
            print(f"[red][X] Error: {error_msg}[/red]")
            raise ValueError(error_msg)

        try:
            # Try to import django-auth-ldap (will fail if not installed)
            import django_auth_ldap
            from django_auth_ldap.config import LDAPSearch
            import ldap

            # Configure LDAP authentication
            AUTH_LDAP_SERVER_URI = LDAP_CONFIG.LDAP_SERVER_URI
            AUTH_LDAP_BIND_DN = LDAP_CONFIG.LDAP_BIND_DN
            AUTH_LDAP_BIND_PASSWORD = LDAP_CONFIG.LDAP_BIND_PASSWORD

            # Configure user search
            AUTH_LDAP_USER_SEARCH = LDAPSearch(
                LDAP_CONFIG.LDAP_USER_BASE,
                ldap.SCOPE_SUBTREE,
                LDAP_CONFIG.LDAP_USER_FILTER,
            )

            # Map LDAP attributes to Django user model fields
            AUTH_LDAP_USER_ATTR_MAP = {
                "username": LDAP_CONFIG.LDAP_USERNAME_ATTR,
                "first_name": LDAP_CONFIG.LDAP_FIRSTNAME_ATTR,
                "last_name": LDAP_CONFIG.LDAP_LASTNAME_ATTR,
                "email": LDAP_CONFIG.LDAP_EMAIL_ATTR,
            }

            # Use custom LDAP backend that supports LDAP_CREATE_SUPERUSER
            AUTHENTICATION_BACKENDS = [
                "archivebox.ldap.auth.ArchiveBoxLDAPBackend",
                "django.contrib.auth.backends.RemoteUserBackend",
                "django.contrib.auth.backends.ModelBackend",
            ]

        except ImportError as e:
            from rich import print
            print("[red][X] Error: LDAP_ENABLED=True but required LDAP libraries are not installed![/red]")
            print(f"[red]    {e}[/red]")
            print("[yellow]    To install LDAP support, run:[/yellow]")
            print("[yellow]        pip install archivebox[ldap][/yellow]")
            print("[yellow]    Or manually:[/yellow]")
            print("[yellow]        apt install build-essential python3-dev libsasl2-dev libldap2-dev libssl-dev[/yellow]")
            print("[yellow]        pip install python-ldap django-auth-ldap[/yellow]")
            raise

except ImportError:
    # archivebox.config.ldap not available (shouldn't happen but handle gracefully)
    pass

################################################################################
### Staticfile and Template Settings
################################################################################

STATIC_URL = "/static/"
TEMPLATES_DIR_NAME = "templates"
CUSTOM_TEMPLATES_ENABLED = os.path.isdir(STORAGE_CONFIG.CUSTOM_TEMPLATES_DIR) and os.access(STORAGE_CONFIG.CUSTOM_TEMPLATES_DIR, os.R_OK)
STATICFILES_DIRS = [
    *([str(STORAGE_CONFIG.CUSTOM_TEMPLATES_DIR / "static")] if CUSTOM_TEMPLATES_ENABLED else []),
    # *[
    #     str(plugin_dir / 'static')
    #     for plugin_dir in PLUGIN_DIRS.values()
    #     if (plugin_dir / 'static').is_dir()
    # ],
    # Additional static file dirs from plugins
    str(PACKAGE_DIR / TEMPLATES_DIR_NAME / "static"),
]

TEMPLATE_DIRS = [
    *([str(STORAGE_CONFIG.CUSTOM_TEMPLATES_DIR)] if CUSTOM_TEMPLATES_ENABLED else []),
    # *[
    #     str(plugin_dir / 'templates')
    #     for plugin_dir in PLUGIN_DIRS.values()
    #     if (plugin_dir / 'templates').is_dir()
    # ],
    # Additional template dirs from plugins
    str(PACKAGE_DIR / TEMPLATES_DIR_NAME / "core"),
    str(PACKAGE_DIR / TEMPLATES_DIR_NAME / "admin"),
    str(PACKAGE_DIR / TEMPLATES_DIR_NAME),
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": TEMPLATE_DIRS,
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
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
        "timeout": 10,
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
    # "filestore": {
    #     "NAME": CONSTANTS.FILESTORE_DATABASE_FILE,
    #     **SQLITE_CONNECTION_OPTIONS,
    # },
    # 'cache': {
    #     'NAME': CACHE_DB_PATH,
    #     **SQLITE_CONNECTION_OPTIONS,
    # },
}
MIGRATION_MODULES = {"signal_webhooks": None}

# Django requires DEFAULT_AUTO_FIELD to subclass AutoField (BigAutoField, SmallAutoField, etc.)
# Cannot use UUIDField here until Django 6.0 introduces DEFAULT_PK_FIELD setting
# For now: manually add `id = models.UUIDField(primary_key=True, default=uuid7, ...)` to all models
# OR inherit from ModelWithUUID base class which provides UUID primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"



# class FilestoreDBRouter:
#     """
#     A router to store all the File models in the filestore.sqlite3 database.
#     This data just mirrors what is in the file system, so we want to keep it in a separate database
#     from the main index database to avoid contention.
#     """

#     route_app_labels = {"filestore"}
#     db_name = "filestore"

#     def db_for_read(self, model, **hints):
#         if model._meta.app_label in self.route_app_labels:
#             return self.db_name
#         return 'default'

#     def db_for_write(self, model, **hints):
#         if model._meta.app_label in self.route_app_labels:
#             return self.db_name
#         return 'default'

#     def allow_relation(self, obj1, obj2, **hints):
#         if obj1._meta.app_label in self.route_app_labels or obj2._meta.app_label in self.route_app_labels:
#             return obj1._meta.app_label == obj2._meta.app_label
#         return None

#     def allow_migrate(self, db, app_label, model_name=None, **hints):
#         if app_label in self.route_app_labels:
#             return db == self.db_name
#         return db == "default"

DATABASE_ROUTERS = []

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    # 'sqlite': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'cache'},
    # 'dummy': {'BACKEND': 'django.core.cache.backends.dummy.DummyCache'},
    # 'filebased': {"BACKEND": "django.core.cache.backends.filebased.FileBasedCache", "LOCATION": CACHE_DIR / 'cache_filebased'},
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


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
    # "snapshots": {
    #     "BACKEND": "django.core.files.storage.FileSystemStorage",
    #     "OPTIONS": {
    #         "base_url": "/snapshots/",
    #         "location": CONSTANTS.SNAPSHOTS_DIR,
    #     },
    # },
    # "personas": {
    #     "BACKEND": "django.core.files.storage.FileSystemStorage",
    #     "OPTIONS": {
    #         "base_url": "/personas/",
    #         "location": PERSONAS_DIR,
    #     },
    # },
}

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

################################################################################
### Security Settings
################################################################################

SECRET_KEY = SERVER_CONFIG.SECRET_KEY or get_random_string(50, "abcdefghijklmnopqrstuvwxyz0123456789_")

ALLOWED_HOSTS = SERVER_CONFIG.ALLOWED_HOSTS.split(",")
CSRF_TRUSTED_ORIGINS = list(set(SERVER_CONFIG.CSRF_TRUSTED_ORIGINS.split(",")))

# automatically fix case when user sets ALLOWED_HOSTS (e.g. to archivebox.example.com)
# but forgets to add https://archivebox.example.com to CSRF_TRUSTED_ORIGINS
for hostname in ALLOWED_HOSTS:
    https_endpoint = f"https://{hostname}"
    if hostname != "*" and https_endpoint not in CSRF_TRUSTED_ORIGINS:
        print(f"[!] WARNING: {https_endpoint} from ALLOWED_HOSTS should be added to CSRF_TRUSTED_ORIGINS")
        CSRF_TRUSTED_ORIGINS.append(https_endpoint)

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_AGE = 1209600  # 2 weeks
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = False

SESSION_ENGINE = "django.contrib.sessions.backends.db"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

DATA_UPLOAD_MAX_NUMBER_FIELDS = None
DATA_UPLOAD_MAX_MEMORY_SIZE = 26_214_400  # 25MB

################################################################################
### Shell Settings
################################################################################

SHELL_PLUS = "ipython"
SHELL_PLUS_PRINT_SQL = False
IPYTHON_ARGUMENTS = ["--no-confirm-exit", "--no-banner"]
IPYTHON_KERNEL_DISPLAY_NAME = "ArchiveBox Django Shell"
if IS_SHELL:
    os.environ["PYTHONSTARTUP"] = str(PACKAGE_DIR / "misc" / "shell_welcome_message.py")


################################################################################
### Internationalization & Localization Settings
################################################################################

LANGUAGE_CODE = "en-us"
USE_I18N = True
USE_TZ = True
DATETIME_FORMAT = "Y-m-d h:i:s A"
SHORT_DATETIME_FORMAT = "Y-m-d h:i:s A"
TIME_ZONE = CONSTANTS.TIMEZONE  # django convention is TIME_ZONE, archivebox config uses TIMEZONE, they are equivalent


from django.conf.locale.en import formats as en_formats  # type: ignore

en_formats.DATETIME_FORMAT = DATETIME_FORMAT  # monkey patch en_format default with our preferred format
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
SIGNAL_WEBHOOKS_CUSTOM_MODEL = "archivebox.api.models.OutboundWebhook"
SIGNAL_WEBHOOKS = {
    "HOOKS": {
        # ... is a special sigil value that means "use the default autogenerated hooks"
        "django.contrib.auth.models.User": ...,
        "archivebox.core.models.Snapshot": ...,
        "archivebox.core.models.ArchiveResult": ...,
        "archivebox.core.models.Tag": ...,
        "archivebox.api.models.APIToken": ...,
    },
}

# Avoid background threads touching sqlite connections (especially during tests/migrations).
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    SIGNAL_WEBHOOKS["TASK_HANDLER"] = "signal_webhooks.handlers.sync_task_handler"

################################################################################
### Admin Data View Settings
################################################################################

ADMIN_DATA_VIEWS = {
    "NAME": "Environment",
    "URLS": [
        {
            "route": "config/",
            "view": "archivebox.core.views.live_config_list_view",
            "name": "Configuration",
            "items": {
                "route": "<str:key>/",
                "view": "archivebox.core.views.live_config_value_view",
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
        # Additional admin data views from plugins
    ],
}


################################################################################
### Debug Settings
################################################################################

# only enable debug toolbar when in DEBUG mode with --nothreading (it doesnt work in multithreaded mode)
DEBUG_TOOLBAR = False
DEBUG_TOOLBAR = DEBUG_TOOLBAR and DEBUG and ("--nothreading" in sys.argv) and ("--reload" not in sys.argv)
if DEBUG_TOOLBAR:
    try:
        import debug_toolbar  # noqa

        DEBUG_TOOLBAR = True
    except ImportError:
        DEBUG_TOOLBAR = False

if DEBUG_TOOLBAR:
    INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
    INTERNAL_IPS = ["0.0.0.0", "127.0.0.1", "*"]
    DEBUG_TOOLBAR_CONFIG = {
        "SHOW_TOOLBAR_CALLBACK": lambda request: True,
        "RENDER_PANELS": True,
    }
    DEBUG_TOOLBAR_PANELS = [
        "debug_toolbar.panels.history.HistoryPanel",
        "debug_toolbar.panels.versions.VersionsPanel",
        "debug_toolbar.panels.timer.TimerPanel",
        "debug_toolbar.panels.settings.SettingsPanel",
        "debug_toolbar.panels.headers.HeadersPanel",
        "debug_toolbar.panels.request.RequestPanel",
        "debug_toolbar.panels.sql.SQLPanel",
        "debug_toolbar.panels.staticfiles.StaticFilesPanel",
        # 'debug_toolbar.panels.templates.TemplatesPanel',
        "debug_toolbar.panels.cache.CachePanel",
        "debug_toolbar.panels.signals.SignalsPanel",
        "debug_toolbar.panels.logging.LoggingPanel",
        "debug_toolbar.panels.redirects.RedirectsPanel",
        "debug_toolbar.panels.profiling.ProfilingPanel",
        "djdt_flamegraph.FlamegraphPanel",
    ]
    MIDDLEWARE = [*MIDDLEWARE, "debug_toolbar.middleware.DebugToolbarMiddleware"]

if DEBUG:
    from django_autotyping.typing import AutotypingSettingsDict

    INSTALLED_APPS += ["django_autotyping"]
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


# import ipdb; ipdb.set_trace()
