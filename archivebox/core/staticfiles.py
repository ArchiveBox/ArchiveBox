from django.conf import settings
from django.contrib.staticfiles.storage import StaticFilesStorage

from archivebox.core.context_processors import get_static_cache_key


class VersionedStaticFilesStorage(StaticFilesStorage):
    def url(self, name):
        url = super().url(name)
        if url.startswith(settings.STATIC_URL):
            # A directory prefix also versions relative CSS imports, fonts,
            # icon sprites, and JavaScript module imports.
            path = url.removeprefix(settings.STATIC_URL)
            return f"{settings.STATIC_URL}v/{get_static_cache_key()}/{path}"
        return url
