"""Exercise real CLI migrations and HTTP views in isolated configured processes."""

import pytest

from archivebox.tests.conftest import run_archivebox_cmd


@pytest.mark.parametrize("mode,enabled,admin", [("open", True, False), ("approval", True, True), ("open", False, False)])
def test_allauth_registration_and_login(initialized_archive, mode, enabled, admin):
    env = {
        "ALLAUTH_ENABLED": "true",
        "REGISTRATION_ENABLED": str(enabled),
        "REGISTRATION_MODE": mode,
        "DEFAULT_USER_PERMISSIONS": "admin" if admin else "none",
        "SERVER_SECURITY_MODE": "safe-onedomain-nojsreplay",
        "BASE_URL": "http://testserver",
    }
    migrated = run_archivebox_cmd(["manage", "migrate", "--noinput"], cwd=initialized_archive, env=env, default_cli_env=True)
    assert migrated.returncode == 0, migrated.stderr
    script = """
from django.test import Client
from django.contrib.auth import get_user_model
from django.conf import settings
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from archivebox.core.admin_site import archivebox_admin
assert EmailAddress in archivebox_admin._registry
assert SocialAccount in archivebox_admin._registry
User = get_user_model()
c = Client(enforce_csrf_checks=True)
r = c.get('/admin/login/')
assert r.status_code == 200 and b'first-admin-form' in r.content
r = c.get('/accounts/login/')
assert r.status_code == 200, r.content
assert r.headers.get('X-Frame-Options') == 'DENY'
assert r.headers.get('Content-Security-Policy') == "frame-ancestors 'none'"
assert b'Forgot your password?' in r.content
assert (b'Create an account' in r.content) == settings.CONFIG.REGISTRATION_ENABLED
csrf = c.cookies[settings.CSRF_COOKIE_NAME].value
r = c.post('/accounts/signup/', {'email': 'new@example.com', 'username': 'newuser', 'password1': 'Sufficient-Test-Pass123!', 'password2': 'Sufficient-Test-Pass123!', 'csrfmiddlewaretoken': csrf})
user = User.objects.filter(username='newuser').first()
if settings.CONFIG.REGISTRATION_ENABLED:
    assert user is not None, r.content
    assert user.is_active == (settings.CONFIG.REGISTRATION_MODE == 'open')
    assert user.is_superuser == (settings.CONFIG.DEFAULT_USER_PERMISSIONS == 'admin')
    assert user.is_staff == user.is_superuser
    assert ('_auth_user_id' in c.session) == user.is_active
else:
    assert r.status_code == 200 and b'Sign Up Closed' in r.content, (r.status_code, r.content)
    assert user is None
# Existing username/password users retain access even with no EmailAddress migration.
legacy = User.objects.create_superuser('legacy', 'legacy@example.com', 'Sufficient-Test-Pass123!')
c = Client(enforce_csrf_checks=True)
r = c.get('/accounts/login/')
csrf = c.cookies[settings.CSRF_COOKIE_NAME].value
r = c.post('/accounts/login/', {'login': 'legacy', 'password': 'Sufficient-Test-Pass123!', 'csrfmiddlewaretoken': csrf, 'next': 'https://evil.invalid/'})
assert r.status_code == 302 and 'evil.invalid' not in r.url, (r.status_code, r.content)
assert c.session['_auth_user_id'] == str(legacy.pk)
r = c.get('/accounts/3rdparty/')
assert r.status_code == 200 and b'/accounts/password/change/' in r.content and b'/accounts/email/' in r.content
for path in ('/admin/account/emailaddress/', '/admin/socialaccount/socialaccount/'):
    r = c.get(path)
    assert r.status_code == 200, (path, r.content)
r = c.get('/accounts/logout/')
assert r.status_code == 200 and c.session['_auth_user_id'] == str(legacy.pk)
assert c.post('/accounts/logout/').status_code == 403
r = c.post('/accounts/logout/', {'csrfmiddlewaretoken': c.cookies[settings.CSRF_COOKIE_NAME].value})
assert r.status_code == 302 and '_auth_user_id' not in c.session
r = c.get('/admin/login/')
assert b'Sign in with SSO or email' in r.content
assert b'id="login-form"' in r.content
print('AUTH_FLOW_OK')
"""
    result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=initialized_archive, env=env, default_cli_env=True)
    assert result.returncode == 0, result.stderr or result.stdout
    assert isinstance(result.stdout, str) and "AUTH_FLOW_OK" in result.stdout


def test_installed_allauth_stays_disabled(initialized_archive):
    script = """
from django.conf import settings
from django.test import Client
from django.urls import resolve
assert not settings.ALLAUTH_ENABLED
assert 'allauth' not in settings.INSTALLED_APPS
r = Client().get('/accounts/login/?next=/add/')
assert r.status_code == 302 and r.url == '/admin/login/?next=/add/'
print('DISABLED_OK')
"""
    result = run_archivebox_cmd(
        ["manage", "shell", "-c", script],
        cwd=initialized_archive,
        env={"ALLAUTH_ENABLED": "false", "SERVER_SECURITY_MODE": "safe-onedomain-nojsreplay", "BASE_URL": "http://testserver"},
        default_cli_env=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert isinstance(result.stdout, str) and "DISABLED_OK" in result.stdout


def test_noadmin_mode_blocks_sso_and_password_login(initialized_archive):
    script = """
from django.conf import settings
from django.test import Client
assert settings.ALLAUTH_ENABLED
client = Client()
for path in ('/admin/login/', '/accounts/login/', '/accounts/signup/', '/accounts/oidc/company/login/', '/accounts/saml/company/acs/', '/accounts/saml/company/metadata/'):
    for method in ('get', 'post'):
        response = getattr(client, method)(path)
        assert response.status_code == 403, (path, method, response.status_code)
        assert not response.cookies
print('NOADMIN_OK')
"""
    result = run_archivebox_cmd(
        ["manage", "shell", "-c", script],
        cwd=initialized_archive,
        env={"ALLAUTH_ENABLED": "true", "SERVER_SECURITY_MODE": "unsafe-onedomain-noadmin", "BASE_URL": "http://testserver"},
        default_cli_env=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert isinstance(result.stdout, str) and "NOADMIN_OK" in result.stdout


def test_allauth_https_cookie_and_origin_boundaries(initialized_archive):
    env = {
        "ALLAUTH_ENABLED": "true",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
        "BASE_URL": "https://archivebox.example",
    }
    result = run_archivebox_cmd(["manage", "migrate", "--noinput"], cwd=initialized_archive, env=env, default_cli_env=True)
    assert result.returncode == 0, result.stderr
    script = """
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
get_user_model().objects.create_superuser('legacy', 'legacy@example.com', 'Sufficient-Test-Pass123!')
client = Client(enforce_csrf_checks=True)
admin = {'HTTP_HOST': 'admin.archivebox.example', 'secure': True}
response = client.get('/accounts/login/', **admin)
csrf = client.cookies[settings.CSRF_COOKIE_NAME]
assert csrf['secure'] and not csrf['domain']
response = client.post('/accounts/login/', {'login': 'legacy', 'password': 'Sufficient-Test-Pass123!', 'csrfmiddlewaretoken': csrf.value}, HTTP_ORIGIN='https://admin.archivebox.example', **admin)
assert response.status_code == 302, response.content
session = response.cookies[settings.SESSION_COOKIE_NAME]
assert session['secure'] and session['httponly'] and not session['domain']
hint = response.cookies['archivebox_admin_logged_in']
assert hint.value == '1' and hint['domain'] == 'archivebox.example'
# An archived origin cannot submit login/logout, even with a valid CSRF token.
response = client.post('/accounts/logout/', {'csrfmiddlewaretoken': client.cookies[settings.CSRF_COOKIE_NAME].value}, HTTP_ORIGIN='https://example.com.archivebox.example', **admin)
assert response.status_code == 403
assert '_auth_user_id' in client.session
for prefix in ('web', 'api', 'snap-0123456789abcdef0123456789abcdef', 'example.com'):
    isolated = Client(enforce_csrf_checks=True)
    isolated.cookies['archivebox_admin_logged_in'] = '1'
    response = isolated.get('/accounts/login/', HTTP_HOST=f'{prefix}.archivebox.example', secure=True)
    assert response.status_code in (301, 302), (prefix, response.status_code)
    assert response.url.startswith('https://admin.archivebox.example/accounts/login/'), response.url
    assert not response.cookies
# The one-bit hint alone never logs a user into the admin hostname.
anonymous = Client()
anonymous.cookies['archivebox_admin_logged_in'] = '1'
response = anonymous.get('/admin/', **admin)
assert response.status_code == 302 and '/admin/login/' in response.url
print('HTTPS_BOUNDARIES_OK')
"""
    result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=initialized_archive, env=env, default_cli_env=True)
    assert result.returncode == 0, result.stderr or result.stdout
    assert isinstance(result.stdout, str) and "HTTPS_BOUNDARIES_OK" in result.stdout
