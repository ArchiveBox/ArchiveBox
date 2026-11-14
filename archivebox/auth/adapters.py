from typing import cast

from django.contrib.auth.models import User

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings

from archivebox.core.routes_util import is_allowed_archivebox_redirect_url


class ArchiveBoxAccountAdapter(DefaultAccountAdapter):
    def is_safe_url(self, url):
        return is_allowed_archivebox_redirect_url(url, request=self.request)

    def new_user(self, request):
        # New SSO accounts are administrators. Existing-account login/linking
        # never changes permissions; local signup is disabled.
        user = cast(User, super().new_user(request))
        config = settings.CONFIG
        user.is_active = config.REGISTRATION_MODE != "approval"
        user.is_staff = user.is_superuser = True
        return user


class ArchiveBoxSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return settings.CONFIG.REGISTRATION_ENABLED
