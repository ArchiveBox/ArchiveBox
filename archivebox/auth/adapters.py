from typing import cast

from django.contrib.auth.models import User

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings

from archivebox.core.routes_util import is_allowed_archivebox_redirect_url


class ArchiveBoxAccountAdapter(DefaultAccountAdapter):
    def is_safe_url(self, url):
        return is_allowed_archivebox_redirect_url(url, request=self.request)

    def new_user(self, request):
        # Both local signup and the default social adapter use this factory.
        # Existing-account login/linking never reapplies new-user permissions.
        user = cast(User, super().new_user(request))
        config = settings.CONFIG
        user.is_active = config.REGISTRATION_MODE != "approval"
        user.is_staff = user.is_superuser = config.DEFAULT_USER_PERMISSIONS == "admin"
        return user
