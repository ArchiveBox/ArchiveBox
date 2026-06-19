__package__ = "archivebox.auth"

from django.dispatch import receiver


def _get_default_permissions() -> str:
    from archivebox.config.common import get_config

    return get_config().DEFAULT_USER_PERMISSIONS


def _get_or_create_group(name: str):
    from django.contrib.auth.models import Group, Permission

    group, created = Group.objects.get_or_create(name=name)
    if name == "readonly":
        # Grant all view_ permissions
        view_perms = Permission.objects.filter(codename__startswith="view_")
        group.permissions.set(view_perms)
    elif name == "readwrite":
        # Grant view_ and add_/change_ permissions (no delete)
        rw_perms = (
            Permission.objects.filter(codename__startswith="view_")
            | Permission.objects.filter(codename__startswith="add_")
            | Permission.objects.filter(codename__startswith="change_")
        )
        group.permissions.set(rw_perms)
    return group


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

    if level in ("readonly", "readwrite"):
        group = _get_or_create_group(level)
        user.groups.add(group)
        # Django admin requires is_staff=True for any access; group permissions
        # alone are not sufficient. Without this, OIDC/social users get a
        # redirect loop: login -> /admin/ -> /admin/login/ -> OIDC (already
        # authenticated) -> /admin/ -> repeat.
        if not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        return


try:
    from allauth.account.signals import user_signed_up

    @receiver(user_signed_up)
    def on_user_signed_up(sender, request, user, **kwargs):
        _apply_default_permissions(user)

except ImportError:
    pass
