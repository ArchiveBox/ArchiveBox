__package__ = 'archivebox.core'

import re
import os

import shutil
import tempfile
import logging

import pydantic
import django.template

from archivebox.config import CONSTANTS

from ..misc.logging import IS_TTY


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

LOGS_DIR = CONSTANTS.LOGS_DIR

if os.access(LOGS_DIR, os.W_OK) and LOGS_DIR.is_dir():
    ERROR_LOG = (LOGS_DIR / 'errors.log')
else:
    # historically too many edge cases here around creating log dir w/ correct permissions early on
    # if there's an issue on startup, we trash the log and let user figure it out via stdout/stderr
    # print(f'[!] WARNING: data/logs dir does not exist. Logging to temp file: {ERROR_LOG}')
    pass


LOG_LEVEL_DATABASE = 'WARNING'  # if DEBUG else 'WARNING'
LOG_LEVEL_REQUEST = 'WARNING'   # if DEBUG else 'WARNING'



SETTINGS_LOGGING = {
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
            "rich_tracebacks": IS_TTY,
            "filters": ["noisyrequestsfilter"],
            "tracebacks_suppress": [
                django,
                pydantic,
            ],
            "tracebacks_width": shutil.get_terminal_size((100, 10)).columns - 1,
            "tracebacks_word_wrap": False,
            "tracebacks_show_locals": False,
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
            "propagate": False,
        },
        "checks": {
            "handlers": ["default", "logfile"],
            "level": "DEBUG",
            "propagate": False,
        },
        "core": {
            "handlers": ["default", "logfile"],
            "level": "DEBUG",
            "propagate": False,
        },
        "plugins_extractor": {
            "handlers": ["default", "logfile"],
            "level": "DEBUG",
            "propagate": False,
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
            "propagate": False,
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
