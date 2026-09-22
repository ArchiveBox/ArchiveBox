__package__ = "archivebox"


import datetime
import re
import warnings

from daphne import access
import django_stubs_ext
from django.utils import timezone

django_stubs_ext.monkeypatch()


# monkey patch django timezone to add back utc (it was removed in Django 5.0)
setattr(timezone, "utc", datetime.UTC)

# Hide site-packages/sonic/client.py:115: SyntaxWarning
# https://github.com/xmonader/python-sonic-client/pull/18
warnings.filterwarnings("ignore", category=SyntaxWarning, module="sonic")


SENSITIVE_QUERY_PARAM_RE = re.compile(r"(?i)([?&](?:api_key|token|access_token|password|secret)=)([^&#\s]+)")


# Make daphne log requests quieter and easier to read
class ModifiedAccessLogGenerator(access.AccessLogGenerator):
    """Clutge workaround until daphne uses the Python logging framework. https://github.com/django/daphne/pull/473/files"""

    def __call__(self, protocol, action, details):
        if protocol == "http" and action == "complete":
            self.write_entry(
                host=details["client"],
                date=datetime.datetime.now(),
                request="%(method)s %(path)s" % details,
                status=details["status"],
                length=details["size"],
                time_taken=details.get("time_taken"),
            )
            return
        return super().__call__(protocol, action, details)

    def write_entry(self, host, date, request, status=None, length=None, ident=None, user=None, time_taken=None):
        request = SENSITIVE_QUERY_PARAM_RE.sub(r"\1[REDACTED]", request)

        # Ignore noisy requests to staticfiles / favicons / etc.
        if "GET /static/" in request:
            return
        if "GET /health/" in request:
            return
        if "GET /progress.json" in request and (time_taken is None or time_taken < 1.0):
            return
        if "GET /api/v1/crawls/crawl/" in request and "/files/chrome_screencast/latest.jpg" in request:
            return
        if "GET /admin/jsi18n/" in request:
            return
        if request.endswith("/favicon.ico") or request.endswith("/robots.txt") or request.endswith("/screenshot.png"):
            return
        if request.endswith(".css") or request.endswith(".js") or request.endswith(".woff") or request.endswith(".ttf"):
            return
        if str(status) in ("404", "304"):
            return

        # clean up the log format to mostly match the same format as django.conf.settings.LOGGING rich formats
        self.stream.write(
            "%s HTTP     %s %s %s\n"
            % (
                date.strftime("%Y-%m-%d %H:%M:%S"),
                request,
                status or "-",
                "localhost" if host.startswith("127.") else host.split(":")[0],
            ),
        )


access.AccessLogGenerator.write_entry = ModifiedAccessLogGenerator.write_entry  # type: ignore
