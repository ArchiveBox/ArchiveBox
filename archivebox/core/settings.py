__package__ = "archivebox.core"

import importlib
import inspect
import logging
import os
import sys
from importlib.util import find_spec
from pathlib import Path

from django.conf.locale.en import formats as en_formats  # type: ignore

import archivebox
from archivebox.config.django import CONFIG
from archivebox.config.constants import CONSTANTS
from archivebox.core.routes_util import get_admin_base_url, get_api_base_url, get_base_url, normalize_base_url

# DATABASE_ENGINE config selects the backend (sqlite by default); the
# sqlite-vs-postgres helpers live in archivebox.misc.db.
from archivebox.misc.db import is_postgres, postgres_db_params

from .settings_logging import SETTINGS_LOGGING

IS_MIGRATING = "makemigrations" in sys.argv[:3] or "migrate" in sys.argv[:3]
IS_TESTING = "test" in sys.argv[:3]
IS_SHELL = "shell" in sys.argv[:3] or "shell_plus" in sys.argv[:3]
IS_GETTING_VERSION_OR_HELP = "version" in sys.argv or "help" in sys.argv or "--version" in sys.argv or "--help" in sys.argv
PACKAGE_DIR = CONSTANTS.PACKAGE_DIR
logger = logging.getLogger(__name__)

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
LOGOUT_REDIRECT_URL = CONFIG.LOGOUT_REDIRECT_URL

PASSWORD_RESET_URL = "/accounts/password_reset/"
APPEND_SLASH = True

DEBUG = CONFIG.DEBUG or ("--debug" in sys.argv)


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
    "signal_webhooks",  # handles REST API outbound webhooks
    "django_object_actions",  # provides easy Django Admin action buttons on change views
    # Our ArchiveBox-provided apps (use fully qualified names)
    # NOTE: Order matters! Apps with migrations that depend on other apps must come AFTER their dependencies
    # "archivebox.config",  # ArchiveBox config settings (no models, not a real Django app)
    "archivebox.plugins",  # plugin discovery, hook helpers, config UI, and plugin metadata views
    "archivebox.search",  # search backend query helpers, admin search UI, and daemon integrations
    "archivebox.machine",  # handles collecting and storing information about the host machine, network interfaces, binaries, etc.
    "archivebox.workers",  # handles starting and managing background workers and processes (orchestrators and actors)
    "archivebox.personas",  # handles Persona and session management
    "archivebox.core",  # core django model with Snapshot, ArchiveResult, etc. (crawls depends on this)
    "archivebox.crawls",  # handles Crawl and CrawlSchedule models and management (depends on core)
    "archivebox.progressmonitor",  # live progress endpoint and admin monitor template
    "archivebox.api",  # Django-Ninja-based Rest API interfaces, config, APIToken model, etc.
    "archivebox.opencode",
    # 3rd-party apps from PyPI that need to be loaded last
    "admin_data_views",  # handles rendering some convenient automatic read-only views of data in Django admin
    "django_extensions",  # provides Django Debug Toolbar (and other non-debug helpers)
]

DJANGO_OBJECT_ACTIONS_DEFAULT_HTTP_METHOD = "POST"


MIDDLEWARE = [
    "archivebox.core.middleware.TimezoneMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "archivebox.core.middleware.AdminCookieIsolationMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "archivebox.api.middleware.ApiCorsMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "archivebox.core.middleware.ReverseProxyAuthMiddleware",
    "archivebox.core.middleware.ServerSecurityModeMiddleware",
    "archivebox.core.middleware.HostRoutingMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "archivebox.core.middleware.CacheControlMiddleware",
    # Additional middlewares from plugins (if any)
]


################################################################################
### Authentication Settings
################################################################################


AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.RemoteUserBackend",
    "django.contrib.auth.backends.ModelBackend",
    # Additional auth backends (e.g., LDAP) configured via settings
]


# LDAP Authentication Configuration
# Conditionally loaded if LDAP_ENABLED=True and django-auth-ldap is installed
try:
    if CONFIG.LDAP_ENABLED:
        # Validate LDAP configuration
        is_valid, error_msg = CONFIG.validate_ldap_config()
        if not is_valid:
            from rich import print

            print(f"[red][X] Error: {error_msg}[/red]")
            raise ValueError(error_msg)

        try:
            # Try to import django-auth-ldap (will fail if not installed)
            LDAPSearch = importlib.import_module("django_auth_ldap.config").LDAPSearch
            ldap = importlib.import_module("ldap")

            # Configure LDAP authentication
            AUTH_LDAP_SERVER_URI = CONFIG.LDAP_SERVER_URI
            AUTH_LDAP_BIND_DN = CONFIG.LDAP_BIND_DN
            AUTH_LDAP_BIND_PASSWORD = CONFIG.LDAP_BIND_PASSWORD

            # Configure user search
            AUTH_LDAP_USER_SEARCH = LDAPSearch(
                CONFIG.LDAP_USER_BASE,
                getattr(ldap, "SCOPE_SUBTREE", 2),
                CONFIG.LDAP_USER_FILTER,
            )

            # Map LDAP attributes to Django user model fields
            AUTH_LDAP_USER_ATTR_MAP = {
                "username": CONFIG.LDAP_USERNAME_ATTR,
                "first_name": CONFIG.LDAP_FIRSTNAME_ATTR,
                "last_name": CONFIG.LDAP_LASTNAME_ATTR,
                "email": CONFIG.LDAP_EMAIL_ATTR,
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
CUSTOM_TEMPLATES_ENABLED = os.path.isdir(CONSTANTS.CUSTOM_TEMPLATES_DIR) and os.access(CONSTANTS.CUSTOM_TEMPLATES_DIR, os.R_OK)
STATICFILES_DIRS = [
    *([str(CONSTANTS.CUSTOM_TEMPLATES_DIR / "static")] if CUSTOM_TEMPLATES_ENABLED else []),
    str(PACKAGE_DIR / TEMPLATES_DIR_NAME / "static"),
]

TEMPLATE_DIRS = [
    *([str(CONSTANTS.CUSTOM_TEMPLATES_DIR)] if CUSTOM_TEMPLATES_ENABLED else []),
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
                "archivebox.core.context_processors.archivebox_globals",
            ],
        },
    },
]


################################################################################
### External Service Settings
################################################################################

DATABASE_NAME = CONFIG.DATABASE_NAME
SQLITE_JOURNAL_MODE = CONFIG.SQLITE_JOURNAL_MODE
SQLITE_MMAP_SIZE = CONFIG.SQLITE_MMAP_SIZE

SQLITE_CONNECTION_OPTIONS = {
    "ENGINE": "archivebox.core.sqlite_backend",
    "TIME_ZONE": CONSTANTS.TIMEZONE,
    "OPTIONS": {
        # https://gcollazo.com/optimal-sqlite-settings-for-django/
        # https://litestream.io/tips/#busy-timeout
        # https://docs.djangoproject.com/en/5.1/ref/databases/#setting-pragma-options
        "timeout": CONFIG.SQLITE_BUSY_TIMEOUT / 1000,
        "check_same_thread": False,
        # Keep SQLite on Django's default deferred transaction mode. BEGIN
        # IMMEDIATE grabs the write lock as soon as atomic() opens, which is
        # exactly what hurts ArchiveBox on large collections where Python code
        # may do filesystem work before the actual row write. Deferred BEGIN
        # keeps writes statement-scoped unless a caller explicitly opens a
        # transaction around multiple writes.
        "transaction_mode": None,
        "init_command": (
            "PRAGMA foreign_keys=ON;"
            f"PRAGMA busy_timeout = {CONFIG.SQLITE_BUSY_TIMEOUT};"
            f"PRAGMA journal_mode = {SQLITE_JOURNAL_MODE};"
            "PRAGMA synchronous = NORMAL;"
            "PRAGMA temp_store = MEMORY;"
            f"PRAGMA mmap_size = {SQLITE_MMAP_SIZE};"
            "PRAGMA journal_size_limit = 67108864;"
            "PRAGMA cache_size = 2000;"
        ),
    },
}

if is_postgres(CONFIG):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            **postgres_db_params(),
            "OPTIONS": {"connect_timeout": 10},
        },
    }
else:
    DATABASES = {
        "default": {
            "NAME": DATABASE_NAME,
            **SQLITE_CONNECTION_OPTIONS,
        },
    }
MIGRATION_MODULES = {"signal_webhooks": None}

# Django requires DEFAULT_AUTO_FIELD to subclass AutoField (BigAutoField, SmallAutoField, etc.)
# Cannot use UUIDField here until Django 6.0 introduces DEFAULT_PK_FIELD setting
# For now: manually add `id = CompactUUIDField(primary_key=True, default=uuid7, ...)` to all models
# OR inherit from ModelWithUUID base class which provides UUID primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


DATABASE_ROUTERS = []

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
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
            "location": CONSTANTS.ARCHIVE_DIR,
        },
    },
    # "snapshots": {
    #     "BACKEND": "django.core.files.storage.FileSystemStorage",
    #     "OPTIONS": {
    #         "base_url": "/snapshots/",
    #         "location": CONSTANTS.USERS_DIR,
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

# Persist SECRET_KEY on first use. Data dirs created before init wrote a
# SECRET_KEY line — or those whose ArchiveBox.conf was hand-edited to remove
# it — would otherwise sign session cookies with a fresh random key on every
# boot (because the pydantic field's default_factory regenerates), logging
# users out on every server restart. ``archivebox init`` writes this for new
# collections; this branch is the recovery path for the rest.
#
# We can't check ``CONFIG.SECRET_KEY`` for "missing" — pydantic's
# default_factory already filled it with a fresh random value. We have to
# inspect the conf file directly to know whether the value will survive.
SECRET_KEY = CONFIG.SECRET_KEY
try:
    from archivebox.config.configset import BaseConfigSet as _BaseConfigSet

    _persisted_keys = _BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE)
    _secret_persisted = bool((_persisted_keys.get("SECRET_KEY") or "").strip())
except (OSError, RuntimeError, ValueError):
    _secret_persisted = True  # err on the side of NOT touching disk
if not _secret_persisted:
    try:
        from archivebox.config.collection import write_config_file

        write_config_file({"SECRET_KEY": SECRET_KEY})
    except (OSError, RuntimeError, ValueError):
        # Read-only mount, missing data dir, mid-init race — fall back to the
        # in-memory random key. The user will get logged out on the next boot
        # but the server still comes up.
        logger.debug("Unable to persist generated SECRET_KEY", exc_info=True)

ALLOWED_HOSTS = [host.strip() for host in CONFIG.ALLOWED_HOSTS.split(",") if host.strip()]
if (CONFIG.SERVER_SECURITY_MODE == "auto" or CONFIG.USES_SUBDOMAIN_ROUTING) and "*" not in ALLOWED_HOSTS:
    # ArchiveBox owns the effective host policy at request time in auto and
    # subdomain modes: canonical hosts keep the normal app surface, while
    # alternate hosts are downgraded/rejected by get_request_config()/middleware.
    # Django has to admit the Host header first for that existing boundary to run.
    ALLOWED_HOSTS.append("*")
CSRF_TRUSTED_ORIGINS = list({origin.strip() for origin in CONFIG.CSRF_TRUSTED_ORIGINS.split(",") if origin.strip()})

admin_base_url = normalize_base_url(get_admin_base_url())
if admin_base_url and admin_base_url not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(admin_base_url)

api_base_url = normalize_base_url(get_api_base_url())
if api_base_url and api_base_url not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(api_base_url)

# Auto-extend CSRF_TRUSTED_ORIGINS with the explicit ALLOWED_HOSTS entries so
# users who set ALLOWED_HOSTS=archivebox.example.com don't have to also list
# https://archivebox.example.com under CSRF_TRUSTED_ORIGINS. (The previous
# per-host WARNING print was just noise — the auto-append below is the actual
# fix, and the effective CSRF_TRUSTED_ORIGINS gets surfaced once at startup
# from archivebox_server.py.)
for hostname in ALLOWED_HOSTS:
    if hostname == "*":
        continue
    https_endpoint = f"https://{hostname}"
    if https_endpoint not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(https_endpoint)

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# When BASE_URL is an https:// URL the deployment is HTTPS end-to-end, typically
# behind a TLS-terminating proxy/tunnel (such as Cloudflare, Caddy, Traefik, or nginx)
# where the proxy -> archivebox hop is plain HTTP, so
# request.is_secure() / request.scheme would otherwise report http. Honour the
# proxy's X-Forwarded-Proto so first-run URL detection and CSRF origin checks are
# correct. Mark auth cookies Secure once the saved BASE_URL confirms HTTPS.
# Derived from the RESOLVED base URL's scheme — no separate flag to keep in sync.
# get_base_url() also covers deployments that only set CSRF_TRUSTED_ORIGINS (the
# implicit-BASE_URL fallback used on 0.7.x->0.9.x upgrades), so HTTPS hardening
# isn't lost until BASE_URL is migrated. An explicit plain-http base (e.g. local
# http://archivebox.localhost:8000) disables proxy HTTPS handling.
BASE_URL_IS_HTTPS = get_base_url(config=CONFIG).strip().lower().startswith("https://")
if BASE_URL_IS_HTTPS or not CONFIG.BASE_URL:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CSRF_COOKIE_SECURE = BASE_URL_IS_HTTPS
SESSION_COOKIE_SECURE = BASE_URL_IS_HTTPS
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_NAME = f"archivebox_sessionid_{CONSTANTS.COLLECTION_ID}"
CSRF_COOKIE_NAME = f"archivebox_csrftoken_{CONSTANTS.COLLECTION_ID}"
# Auth cookies are intentionally scoped to the exact host that set them so
# the admin session is NOT readable from web.* / api.* — that
# split is a security boundary, not a UX choice. Subdomains that need to
# render an "is the user logged in?" indicator must use the single-bit
# `archivebox_admin_logged_in` hint cookie set by core/middleware.py
# (which IS scoped to the listen-host parent), never widen these.
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
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

en_formats.DATETIME_FORMAT = DATETIME_FORMAT  # monkey patch en_format default with our preferred format
en_formats.SHORT_DATETIME_FORMAT = SHORT_DATETIME_FORMAT


################################################################################
### Logging Settings
################################################################################

LOGGING = SETTINGS_LOGGING


################################################################################
### REST API Outbound Webhooks settings
################################################################################

# Add default webhook configuration to the User model
SIGNAL_WEBHOOKS_CUSTOM_MODEL = "archivebox.api.models.OutboundWebhook"
SIGNAL_WEBHOOKS: dict[str, object] = {
    "TIMEOUT": 30,
    "TASK_HANDLER": "archivebox.api.webhooks.transaction_on_commit_task_handler",
    "ERROR_HANDLER": "archivebox.api.webhooks.warning_error_handler",
    "HOOKS": {
        # ... is a special sigil value that means "use the default autogenerated hooks"
        "django.contrib.auth.models.User": ...,
        "archivebox.crawls.models.Crawl": ...,
        "archivebox.core.models.Snapshot": ...,
        "archivebox.core.models.ArchiveResult": ...,
        "archivebox.core.models.Tag": ...,
        "archivebox.api.models.APIToken": ...,
        "archivebox.personas.models.Persona": ...,
        "archivebox.machine.models.Machine": ...,
        "archivebox.machine.models.Binary": ...,
        "archivebox.machine.models.Process": ...,
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
            "view": "archivebox.plugins.views.plugins_list_view",
            "name": "Plugins",
            "items": {
                "route": "<str:key>/",
                "view": "archivebox.plugins.views.plugin_detail_view",
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
    try:
        import django_autotyping  # noqa
    except ImportError:
        pass
    else:
        INSTALLED_APPS += ["django_autotyping"]
        AUTOTYPING = {
            "STUBS_GENERATION": {
                "LOCAL_STUBS_DIR": PACKAGE_DIR / "typings",
            },
        }

# https://github.com/bensi94/Django-Requests-Tracker (improved version of django-debug-toolbar)
# Must delete archivebox/templates/admin to use because it relies on some things we override
# visit /__requests_tracker__/ to access
DEBUG_REQUESTS_TRACKER = DEBUG and find_spec("requests_tracker") is not None
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
