__package__ = 'archivebox.api'

from typing import Optional

from django.http import HttpRequest
from django.contrib.auth import login
from django.contrib.auth import authenticate
from django.contrib.auth.models import AbstractBaseUser

from ninja.security import HttpBearer, APIKeyQuery, APIKeyHeader, HttpBasicAuth, django_auth_superuser


def auth_using_token(token, request: Optional[HttpRequest]=None) -> Optional[AbstractBaseUser]:
    """Given an API token string, check if a corresponding non-expired APIToken exists, and return its user"""
    from api.models import APIToken        # lazy import model to avoid loading it at urls.py import time
    
    user = None

    submitted_empty_form = token in ('string', '', None)
    if submitted_empty_form:
        user = request.user       # see if user is authed via django session and use that as the default
    else:
        try:
            token = APIToken.objects.get(token=token)
            if token.is_valid():
                user = token.user
        except APIToken.DoesNotExist:
            pass

    if not user:
        print('[❌] Failed to authenticate API user using API Key:', request)

    return None

def auth_using_password(username, password, request: Optional[HttpRequest]=None) -> Optional[AbstractBaseUser]:
    """Given a username and password, check if they are valid and return the corresponding user"""
    user = None
    
    submitted_empty_form = (username, password) in (('string', 'string'), ('', ''), (None, None))
    if submitted_empty_form:
        user = request.user       # see if user is authed via django session and use that as the default
    else:
        user = authenticate(
            username=username,
            password=password,
        )

    if not user:
        print('[❌] Failed to authenticate API user using API Key:', request)

    return user


### Base Auth Types

class APITokenAuthCheck:
    """The base class for authentication methods that use an api.models.APIToken"""
    def authenticate(self, request: HttpRequest, key: Optional[str]=None) -> Optional[AbstractBaseUser]:
        user = auth_using_token(
            token=key,
            request=request,
        )
        if user is not None:
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return user

class UserPassAuthCheck:
    """The base class for authentication methods that use a username & password"""
    def authenticate(self, request: HttpRequest, username: Optional[str]=None, password: Optional[str]=None) -> Optional[AbstractBaseUser]:
        user = auth_using_password(
            username=username,
            password=password,
            request=request,
        )
        if user is not None:
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return user


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
    django_auth_superuser,
    UsernameAndPasswordAuth(),
]
