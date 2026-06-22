__package__ = "archivebox.auth"

from django.dispatch import receiver


def _get_default_permissions() -> str:
    from archivebox.config.common import get_config

    return get_config().DEFAULT_USER_PERMISSIONS


def _apply_default_permissions(user) -> None:
    """Apply DEFAULT_USER_PERMISSIONS to a newly signed-up user."""
    level = _get_default_permissions()

    if level == "none":
        return

    if level == "admin":
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
        return


try:
    from allauth.account.signals import user_signed_up

    @receiver(user_signed_up)
    def on_user_signed_up(sender, request, user, **kwargs):
        _apply_default_permissions(user)

except ImportError:
    pass
