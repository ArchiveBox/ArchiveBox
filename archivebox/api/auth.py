__package__ = "archivebox.api"

from datetime import timedelta

from django.utils import timezone
from django.http import HttpRequest
from django.contrib.auth import authenticate
from django.contrib.auth.models import User

from ninja.security import HttpBearer, APIKeyQuery, APIKeyHeader, HttpBasicAuth
from ninja.errors import HttpError


def get_or_create_api_token(user: User | None):
    from archivebox.api.models import APIToken

    if user and user.is_superuser:
        api_tokens = APIToken.objects.filter(created_by_id=user.pk, expires__gt=timezone.now())
        if api_tokens.exists():
            # unexpired token exists, use it
            api_token = api_tokens.last()
        else:
            # does not exist, create a new one
            api_token = APIToken.objects.create(created_by_id=user.pk, expires=timezone.now() + timedelta(days=30))

        if api_token is None:
            return None
        assert api_token.is_valid(), f"API token is not valid {api_token}"

        return api_token
    return None


def auth_using_token(token: str | None, request: HttpRequest | None = None) -> User | None:
    """Given an API token string, check if a corresponding non-expired APIToken exists, and return its user"""
    from archivebox.api.models import APIToken  # lazy import model to avoid loading it at urls.py import time

    user: User | None = None

    submitted_empty_form = str(token).strip() in ("string", "", "None", "null")
    if not submitted_empty_form:
        try:
            api_token = APIToken.objects.get(token=token)
            if api_token.is_valid() and isinstance(api_token.created_by, User):
                user = api_token.created_by
                if request is not None:
                    setattr(request, "_api_token", api_token)
        except APIToken.DoesNotExist:
            pass

    return user


def auth_using_password(username: str | None, password: str | None, request: HttpRequest | None = None) -> User | None:
    """Given a username and password, check if they are valid and return the corresponding user"""
    user: User | None = None

    submitted_empty_form = (username, password) in (("string", "string"), ("", ""), (None, None))
    if not submitted_empty_form:
        authenticated_user = authenticate(
            username=username,
            password=password,
        )
        if isinstance(authenticated_user, User):
            user = authenticated_user
    return user


### Base Auth Types


def _require_superuser(user: User | None, request: HttpRequest, auth_method: str) -> User | None:
    if user and user.pk:
        request.user = user
        setattr(request, "_api_auth_method", auth_method)
        if not user.is_superuser:
            raise HttpError(403, "Valid credentials but User does not have permission (make sure user.is_superuser=True)")
    return user


### Django-Ninja-Provided Auth Methods


class HeaderTokenAuth(APIKeyHeader):
    """Allow authenticating by passing X-API-Key=xyz as a request header"""

    param_name = "X-ArchiveBox-API-Key"

    def authenticate(self, request: HttpRequest, key: str | None) -> User | None:
        return _require_superuser(auth_using_token(token=key, request=request), request, self.__class__.__name__)


class BearerTokenAuth(HttpBearer):
    """Allow authenticating by passing Bearer=xyz as a request header"""

    def authenticate(self, request: HttpRequest, token: str) -> User | None:
        return _require_superuser(auth_using_token(token=token, request=request), request, self.__class__.__name__)


class QueryParamTokenAuth(APIKeyQuery):
    """Allow authenticating by passing api_key=xyz as a GET/POST query parameter"""

    param_name = "api_key"

    def authenticate(self, request: HttpRequest, key: str | None) -> User | None:
        return _require_superuser(auth_using_token(token=key, request=request), request, self.__class__.__name__)


class UsernameAndPasswordAuth(HttpBasicAuth):
    """Allow authenticating by passing username & password via HTTP Basic Authentication (not recommended)"""

    def authenticate(self, request: HttpRequest, username: str, password: str) -> User | None:
        return _require_superuser(
            auth_using_password(username=username, password=password, request=request),
            request,
            self.__class__.__name__,
        )


class DjangoSessionAuth:
    """Allow authenticating with existing Django session cookies (same-origin only)."""

    def __call__(self, request: HttpRequest) -> User | None:
        return self.authenticate(request)

    def authenticate(self, request: HttpRequest, **kwargs) -> User | None:
        user = getattr(request, "user", None)
        if isinstance(user, User) and user.is_authenticated:
            setattr(request, "_api_auth_method", self.__class__.__name__)
            if not user.is_superuser:
                raise HttpError(403, "Valid session but User does not have permission (make sure user.is_superuser=True)")
            return user
        return None


### Enabled Auth Methods

API_AUTH_METHODS = [
    HeaderTokenAuth(),
    BearerTokenAuth(),
    QueryParamTokenAuth(),
    # django_auth_superuser,       # django admin cookie auth, not secure to use with csrf=False
]
