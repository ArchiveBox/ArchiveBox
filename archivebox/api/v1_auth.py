__package__ = 'archivebox.api'

from typing import Optional

from ninja import Router, Schema
from django.utils import timezone
from datetime import timedelta

from api.models import APIToken
from api.auth import auth_using_token, auth_using_password, get_or_create_api_token


router = Router(tags=['Authentication'], auth=None)


class PasswordAuthSchema(Schema):
    """Schema for a /get_api_token request"""
    username: Optional[str] = None
    password: Optional[str] = None


@router.post("/get_api_token", auth=None, summary='Generate an API token for a given username & password (or currently logged-in user)')             # auth=None because they are not authed yet
def get_api_token(request, auth_data: PasswordAuthSchema):
    user = auth_using_password(
        username=auth_data.username,
        password=auth_data.password,
        request=request,
    )

    if user and user.is_superuser:
        api_token = get_or_create_api_token(user)
        assert api_token is not None, "Failed to create API token"
        return api_token.__json__()
    
    return {"success": False, "errors": ["Invalid credentials"]}



class TokenAuthSchema(Schema):
    """Schema for a /check_api_token request"""
    token: str


@router.post("/check_api_token", auth=None, summary='Validate an API token to make sure its valid and non-expired')        # auth=None because they are not authed yet
def check_api_token(request, token_data: TokenAuthSchema):
    user = auth_using_token(
        token=token_data.token,
        request=request,
    )
    if user:
        return {"success": True, "user_id": str(user.pk)}
    
    return {"success": False, "user_id": None}
