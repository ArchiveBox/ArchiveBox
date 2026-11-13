from typing import cast

from django.contrib.auth.models import User

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings

from archivebox.core.routes_util import is_allowed_archivebox_redirect_url


class ArchiveBoxAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return settings.CONFIG.REGISTRATION_ENABLED

    def is_safe_url(self, url):
        return is_allowed_archivebox_redirect_url(url, request=self.request)

    def save_user(self, request, user, form, commit=True):
        user = cast(User, super().save_user(request, user, form, commit=False))
        config = settings.CONFIG
        user.is_active = config.REGISTRATION_MODE != "approval"
        user.is_staff = user.is_superuser = config.DEFAULT_USER_PERMISSIONS == "admin"
        if commit:
            user.save()
        return user


class ArchiveBoxSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return settings.CONFIG.REGISTRATION_ENABLED

    def save_user(self, request, sociallogin, form=None):
        # The automatic social signup path does not call AccountAdapter.save_user.
        user = cast(User, sociallogin.user)
        config = settings.CONFIG
        user.is_active = config.REGISTRATION_MODE != "approval"
        user.is_staff = user.is_superuser = config.DEFAULT_USER_PERMISSIONS == "admin"
        return super().save_user(request, sociallogin, form)
