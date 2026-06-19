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
    Custom social account adapter that:
    - Enforces the same registration policy as ArchiveBoxAccountAdapter
    - Auto-connects social accounts whose email matches an existing local user
    """

    def is_open_for_signup(self, request, sociallogin):
        if not _get_registration_enabled():
            return False
        if _get_registration_mode() == "invite":
            return False
        return True

    def pre_social_login(self, request, sociallogin):
        """
        If the social account's verified email matches an existing user,
        connect the social account to that user rather than creating a duplicate.
        """
        from django.contrib.auth import get_user_model

        User = get_user_model()

        if sociallogin.is_existing:
            return

        emails = [ea.email for ea in sociallogin.email_addresses if ea.verified]
        for email in emails:
            try:
                existing_user = User.objects.get(email__iexact=email)
                sociallogin.connect(request, existing_user)
                return
            except User.DoesNotExist:
                continue
