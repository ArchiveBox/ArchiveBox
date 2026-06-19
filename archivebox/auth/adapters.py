__package__ = "archivebox.auth"

import importlib

try:
    DefaultAccountAdapter = importlib.import_module("allauth.account.adapter").DefaultAccountAdapter
    DefaultSocialAccountAdapter = importlib.import_module("allauth.socialaccount.adapter").DefaultSocialAccountAdapter
except (ImportError, RuntimeError):

    class DefaultAccountAdapter:  # type: ignore[no-redef]
        """Stub when django-allauth is not installed."""

        pass

    class DefaultSocialAccountAdapter:  # type: ignore[no-redef]
        """Stub when django-allauth is not installed."""

        pass


def _get_registration_enabled() -> bool:
    from archivebox.config.common import get_config

    return get_config().REGISTRATION_ENABLED


def _get_registration_mode() -> str:
    from archivebox.config.common import get_config

    return get_config().REGISTRATION_MODE


class ArchiveBoxAccountAdapter(DefaultAccountAdapter):
    """
    Custom account adapter that enforces ArchiveBox registration policy:
    - REGISTRATION_ENABLED=False → signup form is closed entirely
    - REGISTRATION_MODE="invite" → signup form is closed (invite link required)
    - REGISTRATION_MODE="approval" → user is saved inactive, pending admin activation
    """

    def is_open_for_signup(self, request):
        if not _get_registration_enabled():
            return False
        if _get_registration_mode() == "invite":
            return False
        return True

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        if _get_registration_mode() == "approval":
            user.is_active = False
        if commit:
            user.save()
        return user


class ArchiveBoxSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom social account adapter that enforces the same registration policy
    as ArchiveBoxAccountAdapter for social logins.

    Auto-connecting social accounts by verified email is controlled by the
    django-allauth setting SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT,
    which ArchiveBox exposes as SOCIALACCOUNT_EMAIL_AUTO_CONNECT (default: False).
    See archivebox/config/allauth.py for the security rationale.
    """

    def is_open_for_signup(self, request, sociallogin):
        if not _get_registration_enabled():
            return False
        if _get_registration_mode() == "invite":
            return False
        return True
