__package__ = 'archivebox.core'

import os
import sys
import re
import logging
import tempfile

from pathlib import Path
from django.utils.crypto import get_random_string

from ..config import (
    DEBUG,
    SECRET_KEY,
    ALLOWED_HOSTS,
    PACKAGE_DIR,
    TEMPLATES_DIR_NAME,
    CUSTOM_TEMPLATES_DIR,
    SQL_INDEX_FILENAME,
    OUTPUT_DIR,
    LOGS_DIR,
    TIMEZONE,

    LDAP,
    LDAP_SERVER_URI,
    LDAP_BIND_DN,
    LDAP_BIND_PASSWORD,
    LDAP_USER_BASE,
    LDAP_USER_FILTER,
    LDAP_USERNAME_ATTR,
    LDAP_FIRSTNAME_ATTR,
    LDAP_LASTNAME_ATTR,
    LDAP_EMAIL_ATTR,
)

IS_MIGRATING = 'makemigrations' in sys.argv[:3] or 'migrate' in sys.argv[:3]
IS_TESTING = 'test' in sys.argv[:3] or 'PYTEST_CURRENT_TEST' in os.environ
IS_SHELL = 'shell' in sys.argv[:3] or 'shell_plus' in sys.argv[:3]

################################################################################
### Django Core Settings
################################################################################

WSGI_APPLICATION = 'core.wsgi.application'
ROOT_URLCONF = 'core.urls'

LOGIN_URL = '/accounts/login/'
LOGOUT_REDIRECT_URL = os.environ.get('LOGOUT_REDIRECT_URL', '/')

PASSWORD_RESET_URL = '/accounts/password_reset/'
APPEND_SLASH = True

DEBUG = DEBUG or ('--debug' in sys.argv)

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.admin',

    'core',

    'django_extensions',
]


# For usage with https://www.jetadmin.io/integrations/django
# INSTALLED_APPS += ['jet_django']
# JET_PROJECT = 'archivebox'
# JET_TOKEN = 'some-api-token-here'


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

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.RemoteUserBackend',
    'django.contrib.auth.backends.ModelBackend',
]

if LDAP:
    try:
        import ldap
        from django_auth_ldap.config import LDAPSearch

        global AUTH_LDAP_SERVER_URI
        global AUTH_LDAP_BIND_DN
        global AUTH_LDAP_BIND_PASSWORD
        global AUTH_LDAP_USER_SEARCH
        global AUTH_LDAP_USER_ATTR_MAP

        AUTH_LDAP_SERVER_URI = LDAP_SERVER_URI
        AUTH_LDAP_BIND_DN = LDAP_BIND_DN
        AUTH_LDAP_BIND_PASSWORD = LDAP_BIND_PASSWORD

        assert AUTH_LDAP_SERVER_URI and LDAP_USERNAME_ATTR and LDAP_USER_FILTER, 'LDAP_* config options must all be set if LDAP=True'

        AUTH_LDAP_USER_SEARCH = LDAPSearch(
            LDAP_USER_BASE,
            ldap.SCOPE_SUBTREE,
            '(&(' + LDAP_USERNAME_ATTR + '=%(user)s)' + LDAP_USER_FILTER + ')',
        )

        AUTH_LDAP_USER_ATTR_MAP = {
            'username': LDAP_USERNAME_ATTR,
            'first_name': LDAP_FIRSTNAME_ATTR,
            'last_name': LDAP_LASTNAME_ATTR,
            'email': LDAP_EMAIL_ATTR,
        }

        AUTHENTICATION_BACKENDS = [
            'django_auth_ldap.backend.LDAPBackend',
        ]
    except ModuleNotFoundError:
        sys.stderr.write('[X] Error: Found LDAP=True config but LDAP packages not installed. You may need to run: pip install archivebox[ldap]\n\n')
        # dont hard exit here. in case the user is just running "archivebox version" or "archivebox help", we still want those to work despite broken ldap
        # sys.exit(1)


################################################################################
### Debug Settings
################################################################################

# only enable debug toolbar when in DEBUG mode with --nothreading (it doesnt work in multithreaded mode)
DEBUG_TOOLBAR = DEBUG and ('--nothreading' in sys.argv) and ('--reload' not in sys.argv)
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

################################################################################
### Staticfile and Template Settings
################################################################################

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    *([str(CUSTOM_TEMPLATES_DIR / 'static')] if CUSTOM_TEMPLATES_DIR else []),
    str(Path(PACKAGE_DIR) / TEMPLATES_DIR_NAME / 'static'),
]

TEMPLATE_DIRS = [
    *([str(CUSTOM_TEMPLATES_DIR)] if CUSTOM_TEMPLATES_DIR else []),
    str(Path(PACKAGE_DIR) / TEMPLATES_DIR_NAME / 'core'),
    str(Path(PACKAGE_DIR) / TEMPLATES_DIR_NAME / 'admin'),
    str(Path(PACKAGE_DIR) / TEMPLATES_DIR_NAME),
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

DATABASE_FILE = Path(OUTPUT_DIR) / SQL_INDEX_FILENAME
DATABASE_NAME = os.environ.get("ARCHIVEBOX_DATABASE_NAME", str(DATABASE_FILE))

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATABASE_NAME,
        'OPTIONS': {
            'timeout': 60,
            'check_same_thread': False,
        },
        'TIME_ZONE': TIMEZONE,
        # DB setup is sometimes modified at runtime by setup_django() in config.py
    }
}

CACHE_BACKEND = 'django.core.cache.backends.locmem.LocMemCache'
# CACHE_BACKEND = 'django.core.cache.backends.db.DatabaseCache'
# CACHE_BACKEND = 'django.core.cache.backends.dummy.DummyCache'

CACHES = {
    'default': {
        'BACKEND': CACHE_BACKEND,
        'LOCATION': 'django_cache_default',
    }
}

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


################################################################################
### Security Settings
################################################################################

SECRET_KEY = SECRET_KEY or get_random_string(50, 'abcdefghijklmnopqrstuvwxyz0123456789_')

ALLOWED_HOSTS = ALLOWED_HOSTS.split(',')

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_AGE = 1209600  # 2 weeks
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True

SESSION_ENGINE = "django.contrib.sessions.backends.db"

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


################################################################################
### Shell Settings
################################################################################

SHELL_PLUS = 'ipython'
SHELL_PLUS_PRINT_SQL = False
IPYTHON_ARGUMENTS = ['--no-confirm-exit', '--no-banner']
IPYTHON_KERNEL_DISPLAY_NAME = 'ArchiveBox Django Shell'
if IS_SHELL:
    os.environ['PYTHONSTARTUP'] = str(Path(PACKAGE_DIR) / 'core' / 'welcome_message.py')


################################################################################
### Internationalization & Localization Settings
################################################################################

LANGUAGE_CODE = 'en-us'
USE_I18N = True
USE_L10N = True
USE_TZ = True
DATETIME_FORMAT = 'Y-m-d g:iA'
SHORT_DATETIME_FORMAT = 'Y-m-d h:iA'
TIME_ZONE = TIMEZONE        # django convention is TIME_ZONE, archivebox config uses TIMEZONE, they are equivalent


from django.conf.locale.en import formats as en_formats

en_formats.DATETIME_FORMAT = DATETIME_FORMAT
en_formats.SHORT_DATETIME_FORMAT = SHORT_DATETIME_FORMAT


################################################################################
### Logging Settings
################################################################################

IGNORABLE_404_URLS = [
    re.compile(r'apple-touch-icon.*\.png$'),
    re.compile(r'favicon\.ico$'),
    re.compile(r'robots\.txt$'),
    re.compile(r'.*\.(css|js)\.map$'),
]

class NoisyRequestsFilter(logging.Filter):
    def filter(self, record):
        logline = record.getMessage()

        # ignore harmless 404s for the patterns in IGNORABLE_404_URLS
        for ignorable_url_pattern in IGNORABLE_404_URLS:
            ignorable_log_pattern = re.compile(f'^"GET /.*/?{ignorable_url_pattern.pattern[:-1]} HTTP/.*" (200|30.|404) .+$', re.I | re.M)
            if ignorable_log_pattern.match(logline):
                return 0

        # ignore staticfile requests that 200 or 30*
        ignoreable_200_log_pattern = re.compile(r'"GET /static/.* HTTP/.*" (200|30.) .+', re.I | re.M)
        if ignoreable_200_log_pattern.match(logline):
            return 0

        return 1

if LOGS_DIR.exists():
    ERROR_LOG = (LOGS_DIR / 'errors.log')
else:
    # historically too many edge cases here around creating log dir w/ correct permissions early on
    # if there's an issue on startup, we trash the log and let user figure it out via stdout/stderr
    ERROR_LOG = tempfile.NamedTemporaryFile().name

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
        'logfile': {
            'level': 'ERROR',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': ERROR_LOG,
            'maxBytes': 1024 * 1024 * 25,  # 25 MB
            'backupCount': 10,
        },
    },
    'filters': {
        'noisyrequestsfilter': {
            '()': NoisyRequestsFilter,
        }
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'logfile'],
            'level': 'INFO',
            'filters': ['noisyrequestsfilter'],
        },
        'django.server': {
            'handlers': ['console', 'logfile'],
            'level': 'INFO',
            'filters': ['noisyrequestsfilter'],
        }
    },
}
