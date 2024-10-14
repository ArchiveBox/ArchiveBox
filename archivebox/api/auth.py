__package__ = 'archivebox.api'

from typing import Any, Optional, cast
from datetime import timedelta

from django.http import HttpRequest
from django.utils import timezone
from django.contrib.auth import login
from django.contrib.auth import authenticate
from django.contrib.auth.models import AbstractBaseUser

from ninja.security import HttpBearer, APIKeyQuery, APIKeyHeader, HttpBasicAuth, django_auth_superuser
from ninja.errors import HttpError


def get_or_create_api_token(user):
    from api.models import APIToken
    
    if user and user.is_superuser:
        api_tokens = APIToken.objects.filter(created_by_id=user.pk, expires__gt=timezone.now())
        if api_tokens.exists():
            # unexpired token exists, use it
            api_token = api_tokens.last()
        else:
            # does not exist, create a new one
            api_token = APIToken.objects.create(created_by_id=user.pk, expires=timezone.now() + timedelta(days=30))
        
        assert api_token.is_valid(), f"API token is not valid {api_token}"

        return api_token
    return None


def auth_using_token(token, request: Optional[HttpRequest]=None) -> Optional[AbstractBaseUser]:
    """Given an API token string, check if a corresponding non-expired APIToken exists, and return its user"""
    from api.models import APIToken        # lazy import model to avoid loading it at urls.py import time
    
    user = None

    submitted_empty_form = str(token).strip() in ('string', '', 'None', 'null')
    if not submitted_empty_form:
        try:
            token = APIToken.objects.get(token=token)
            if token.is_valid():
                user = token.created_by
                request._api_token = token
        except APIToken.DoesNotExist:
            pass

    if not user:
        # print('[❌] Failed to authenticate API user using API Key:', request)
        return None
    
    return cast(AbstractBaseUser, user)

def auth_using_password(username, password, request: Optional[HttpRequest]=None) -> Optional[AbstractBaseUser]:
    """Given a username and password, check if they are valid and return the corresponding user"""
    user = None
    
    submitted_empty_form = (username, password) in (('string', 'string'), ('', ''), (None, None))
    if not submitted_empty_form:
        user = authenticate(
            username=username,
            password=password,
        )

    if not user:
        # print('[❌] Failed to authenticate API user using API Key:', request)
        user = None

    return cast(AbstractBaseUser | None, user)


### Base Auth Types


class APITokenAuthCheck:
    """The base class for authentication methods that use an api.models.APIToken"""
    def authenticate(self, request: HttpRequest, key: Optional[str]=None) -> Optional[AbstractBaseUser]:
        request.user = auth_using_token(
            token=key,
            request=request,
        )
        if request.user and request.user.pk:
            # Don't set cookie/persist login ouside this erquest, user may be accessing the API from another domain (CSRF/CORS):
            # login(request, request.user, backend='django.contrib.auth.backends.ModelBackend')
            request._api_auth_method = self.__class__.__name__

            if not request.user.is_superuser:
                raise HttpError(403, 'Valid API token but User does not have permission (make sure user.is_superuser=True)')
        return request.user


class UserPassAuthCheck:
    """The base class for authentication methods that use a username & password"""
    def authenticate(self, request: HttpRequest, username: Optional[str]=None, password: Optional[str]=None) -> Optional[AbstractBaseUser]:
        request.user = auth_using_password(
            username=username,
            password=password,
            request=request,
        )
        if request.user and request.user.pk:
            # Don't set cookie/persist login ouside this erquest, user may be accessing the API from another domain (CSRF/CORS):
            # login(request, request.user, backend='django.contrib.auth.backends.ModelBackend')
            request._api_auth_method = self.__class__.__name__

            if not request.user.is_superuser:
                raise HttpError(403, 'Valid API token but User does not have permission (make sure user.is_superuser=True)')

        return request.user


### Django-Ninja-Provided Auth Methods

class HeaderTokenAuth(APITokenAuthCheck, APIKeyHeader):
    """Allow authenticating by passing X-API-Key=xyz as a request header"""
    param_name = "X-ArchiveBox-API-Key"

class BearerTokenAuth(APITokenAuthCheck, HttpBearer):
    """Allow authenticating by passing Bearer=xyz as a request header"""
    pass

class QueryParamTokenAuth(APITokenAuthCheck, APIKeyQuery):
    """Allow authenticating by passing api_key=xyz as a GET/POST query parameter"""
    param_name = "api_key"

class UsernameAndPasswordAuth(UserPassAuthCheck, HttpBasicAuth):
    """Allow authenticating by passing username & password via HTTP Basic Authentication (not recommended)"""
    pass

### Enabled Auth Methods

API_AUTH_METHODS = [
    HeaderTokenAuth(),
    BearerTokenAuth(),
    QueryParamTokenAuth(), 
    # django_auth_superuser,       # django admin cookie auth, not secure to use with csrf=False
    UsernameAndPasswordAuth(),
]
