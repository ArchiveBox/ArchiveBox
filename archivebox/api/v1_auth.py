__package__ = "archivebox.api"

from django.http import HttpRequest

from ninja import Router, Schema

from archivebox.api.auth import auth_using_token, auth_using_password, get_or_create_api_token, HeaderTokenAuth, BearerTokenAuth


router = Router(tags=["Authentication"], auth=None)


class PasswordAuthSchema(Schema):
    """Schema for a /get_api_token request"""

    username: str | None = None
    password: str | None = None


@router.post(
    "/get_api_token",
    auth=None,
    summary="Generate an API token for a given username & password (or currently logged-in user)",
)  # auth=None because they are not authed yet
def get_api_token(request: HttpRequest, auth_data: PasswordAuthSchema):
    user = auth_using_password(
        username=auth_data.username,
        password=auth_data.password,
        request=request,
    )

    if user and user.is_superuser:
        api_token = get_or_create_api_token(user)
        assert api_token is not None, "Failed to create API token"
        return {
            "success": True,
            "user_id": str(user.pk),
            "username": user.username,
            "token": api_token.token,
            "expires": api_token.expires.isoformat() if api_token.expires else None,
        }

    return {"success": False, "errors": ["Invalid credentials"]}


class TokenAuthSchema(Schema):
    """Schema for a /check_api_token request"""

    token: str


@router.post(
    "/check_api_token",
    auth=None,
    summary="Validate an API token to make sure its valid and non-expired",
)  # auth=None because they are not authed yet
def check_api_token(request: HttpRequest, token_data: TokenAuthSchema):
    user = auth_using_token(
        token=token_data.token,
        request=request,
    )
    if user:
        return {"success": True, "user_id": str(user.pk)}

    return {"success": False, "user_id": None}


@router.post(
    "/browser_session",
    auth=[HeaderTokenAuth(), BearerTokenAuth()],
    summary="Exchange an administrator API key for a normal browser session",
)
def browser_session(request: HttpRequest):
    from django.conf import settings
    from django.contrib.auth import login
    from django.http import JsonResponse
    from django.utils import timezone
    from ninja.errors import HttpError
    from archivebox.core.routes_util import get_admin_base_url

    user = request.auth
    if not user.is_active or not user.is_superuser:
        raise HttpError(403, "An active administrator is required")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    # A browser session must not outlive the key used to establish it.
    token = request._api_token
    lifetime = settings.SESSION_COOKIE_AGE
    if token.expires:
        lifetime = min(lifetime, max(0, int((token.expires - timezone.now()).total_seconds())))
    request.session.set_expiry(lifetime)
    request.session.save()
    response = JsonResponse(
        {
            "admin_url": get_admin_base_url(request=request).rstrip("/") + "/admin/",
            "cookie": {
                "name": settings.SESSION_COOKIE_NAME,
                "value": request.session.session_key,
                "expires": request.session.get_expiry_date().timestamp(),
                "secure": settings.SESSION_COOKIE_SECURE,
            },
        },
    )
    # The native client installs a host-only HttpOnly cookie on the admin origin;
    # API and admin hosts can differ, so a Set-Cookie on the API host is insufficient.
    response["Cache-Control"] = "no-store"
    return response
