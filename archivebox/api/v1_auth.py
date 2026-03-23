__package__ = "archivebox.api"

from django.http import HttpRequest

from ninja import Router, Schema

from archivebox.api.auth import auth_using_token, auth_using_password, get_or_create_api_token


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
