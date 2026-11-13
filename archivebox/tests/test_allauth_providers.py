# ci-runner: hosted
# Requires a Docker daemon; stock NAS runners deliberately have no Docker socket.
# ci-workers: 1
"""Real Keycloak + Chromium acceptance tests for OIDC and signed SAML SSO.

Requires Docker and archivebox[saml]. No provider responses are simulated.
"""

import base64
import json
import secrets
import subprocess
import time
from urllib.parse import urlsplit

import pytest
import requests
from playwright.sync_api import sync_playwright
from lxml import html

from archivebox.tests.conftest import (
    get_free_port,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_archivebox_process,
)


@pytest.fixture(scope="module")
def keycloak():
    port = get_free_port()
    password = secrets.token_urlsafe(24)
    name = f"archivebox-sso-test-{secrets.token_hex(6)}"
    subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "-p",
            f"127.0.0.1:{port}:8080",
            "-e",
            "KC_BOOTSTRAP_ADMIN_USERNAME=admin",
            "-e",
            f"KC_BOOTSTRAP_ADMIN_PASSWORD={password}",
            "quay.io/keycloak/keycloak:26.4.7",
            "start-dev",
        ],
        check=True,
        capture_output=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                response = requests.get(f"{base}/realms/master", timeout=1)
                if response.status_code == 200:
                    break
            except requests.ConnectionError:
                pass
            time.sleep(0.2)
        else:
            logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
            pytest.fail(f"Keycloak failed to start: {logs.stdout}\n{logs.stderr}")
        yield base, password
    finally:
        subprocess.run(["docker", "rm", "--force", name], check=True, capture_output=True)


@pytest.mark.parametrize("protocol", ["oidc", "saml"])
@pytest.mark.parametrize(
    "mode,security_mode",
    [
        *(
            ("open", security)
            for security in (
                "auto",
                "auto-onedomain",
                "safe-subdomains-fullreplay",
                "safe-onedomain-nojsreplay",
                "danger-onedomain-fullreplay",
            )
        ),
        *((policy, "safe-subdomains-fullreplay") for policy in ("approval", "closed", "collision", "connect")),
    ],
)
def test_real_provider_login(keycloak, initialized_archive, browser_runtime, protocol, mode, security_mode):
    base, admin_password = keycloak
    response = requests.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": "admin",
            "password": admin_password,
        },
        timeout=10,
    )
    response.raise_for_status()
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    realm = f"archivebox-{secrets.token_hex(5)}"
    issuer = f"{base}/realms/{realm}"
    port = get_free_port()
    isolated = security_mode in {"auto", "safe-subdomains-fullreplay"}
    base_host = "127.0.0.1" if security_mode == "auto-onedomain" else "archivebox.localhost"
    admin_host = f"admin.{base_host}" if isolated else base_host
    origin = f"http://{admin_host}:{port}"
    secret = secrets.token_urlsafe(24)
    password = secrets.token_urlsafe(24)
    metadata = f"{origin}/accounts/saml/keycloak/metadata/"
    clients = [
        {
            "clientId": "archivebox",
            "protocol": "openid-connect",
            "secret": secret,
            "publicClient": False,
            "standardFlowEnabled": True,
            "redirectUris": [f"{origin}/accounts/oidc/keycloak/login/callback/"],
            "defaultClientScopes": ["profile", "email"],
        },
        {
            "clientId": metadata,
            "protocol": "saml",
            "redirectUris": [f"{origin}/accounts/saml/keycloak/acs/"],
            "attributes": {
                "saml.assertion.signature": "true",
                "saml.server.signature": "true",
                "saml.client.signature": "false",
                "saml.force.post.binding": "true",
                "saml.authnstatement": "true",
                "saml_name_id_format": "persistent",
                "saml_assertion_consumer_url_post": f"{origin}/accounts/saml/keycloak/acs/",
                "saml_single_logout_service_url_redirect": f"{origin}/accounts/saml/keycloak/sls/",
            },
            "protocolMappers": [
                {
                    "name": field,
                    "protocol": "saml",
                    "protocolMapper": "saml-user-property-mapper",
                    "config": {"user.attribute": field, "attribute.name": field, "attribute.nameformat": "Basic"},
                }
                for field in ("email", "username", "firstName", "lastName")
            ],
        },
    ]
    response = requests.post(
        f"{base}/admin/realms",
        headers=headers,
        json={
            "realm": realm,
            "enabled": True,
            "sslRequired": "none",
            "clients": clients,
            "users": [
                {
                    "username": "sso-user",
                    "email": "sso@example.com",
                    "emailVerified": True,
                    "enabled": True,
                    "firstName": "SSO",
                    "lastName": "User",
                    "credentials": [{"type": "password", "value": password, "temporary": False}],
                },
            ],
        },
        timeout=10,
    )
    assert response.status_code == 201, response.text
    providers = {
        "openid_connect": {
            "OAUTH_PKCE_ENABLED": True,
            "APPS": [
                {
                    "provider_id": "keycloak",
                    "name": "Keycloak OIDC",
                    "client_id": "archivebox",
                    "secret": secret,
                    "settings": {"server_url": issuer},
                },
            ],
        },
        "saml": {
            "APPS": [
                {
                    "provider_id": issuer,
                    "name": "Keycloak SAML",
                    "client_id": "keycloak",
                    "settings": {
                        "idp": {"entity_id": issuer, "metadata_url": f"{issuer}/protocol/saml/descriptor"},
                        "attribute_mapping": {"email": "email", "username": "username", "first_name": "firstName", "last_name": "lastName"},
                        "advanced": {"want_assertion_signed": True},
                    },
                },
            ],
        },
    }
    env = {
        "ALLAUTH_ENABLED": "true",
        "REGISTRATION_ENABLED": str(mode not in {"closed", "connect"}),
        "REGISTRATION_MODE": "approval" if mode == "approval" else "open",
        "DEFAULT_USER_PERMISSIONS": "admin",
        "SOCIALACCOUNT_PROVIDERS": json.dumps(providers),
        "BASE_URL": f"http://{base_host}:{port}",
        "SERVER_SECURITY_MODE": "auto" if security_mode == "auto-onedomain" else security_mode,
    }
    migrated = run_archivebox_cmd(["manage", "migrate", "--noinput"], cwd=initialized_archive, env=env, default_cli_env=True)
    assert migrated.returncode == 0, migrated.stderr
    if mode in {"collision", "connect"}:
        result = run_archivebox_cmd(
            [
                "manage",
                "shell",
                "-c",
                "from django.contrib.auth import get_user_model; get_user_model().objects.create_superuser('existing', 'sso@example.com', 'Local-Password123!')",
            ],
            cwd=initialized_archive,
            env=env,
            default_cli_env=True,
        )
        assert result.returncode == 0, result.stderr
    proc = start_archivebox_server(initialized_archive, port=port, env=env, log_name="sso-server.log")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=str(browser_runtime["chrome_binary"]),
                headless=True,
                args=browser_runtime["chrome_args"],
            )
            context = browser.new_context()
            page = context.new_page()
            saml_posts = []
            page.on(
                "request",
                lambda request: (
                    saml_posts.append(request.post_data) if request.url.endswith("/acs/") and request.method == "POST" else None
                ),
            )
            page.goto(f"{origin}/accounts/login/")
            assert page.get_by_text("Keycloak OIDC", exact=True).count() == 1
            assert page.get_by_text("Keycloak SAML", exact=True).count() == 1
            page.screenshot(path=str(initialized_archive / "login.png"), full_page=True)
            if mode == "connect":
                page.locator("#id_login").fill("existing")
                page.locator("#id_password").fill("Local-Password123!")
                page.get_by_role("button", name="Log in", exact=True).click()
                page.goto(f"{origin}/accounts/3rdparty/")
            page.get_by_text(f"Keycloak {protocol.upper()}", exact=True).click()
            page.screenshot(path=str(initialized_archive / "provider-confirmation.png"), full_page=True)
            # allauth's CSRF-protected confirmation precedes the provider redirect.
            page.get_by_role("button", name="Continue").click()
            page.locator("#username").fill("sso-user")
            page.locator("#password").fill(password)
            page.locator("#kc-login").click()
            page.wait_for_url(f"{origin}/**")
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(initialized_archive / f"{protocol}-{mode}.png"), full_page=True)
            if mode == "connect":
                assert "Account Connections" in page.content(), page.content()
                page.goto(f"{origin}/admin/")
                assert urlsplit(page.url).path == "/admin/"
                page.goto(f"{origin}/accounts/logout/")
                page.get_by_role("button", name="Sign Out").click()
                # Linking a pre-existing account permits later SSO login even
                # while registration remains closed. The IdP session is live.
                page.goto(f"{origin}/accounts/login/")
                page.get_by_text(f"Keycloak {protocol.upper()}", exact=True).click()
                page.get_by_role("button", name="Continue").click()
                page.wait_for_url(f"{origin}/**")
                page.goto(f"{origin}/admin/")
                assert urlsplit(page.url).path == "/admin/"
                page.goto(f"{origin}/accounts/logout/")
                page.get_by_role("button", name="Sign Out").click()
            elif mode == "approval":
                assert "inactive" in page.content().lower(), page.content()
            elif mode in {"closed", "collision"}:
                expected = "Sign Up Closed" if mode == "closed" else "Sign Up"
                assert expected in page.content(), page.content()
                page.goto(f"{origin}/admin/")
                assert "/admin/login/" in page.url
            else:
                private_replay_url = None
                page.goto(f"{origin}/admin/")
                assert urlsplit(page.url).path == "/admin/", page.content()
                cookies = context.cookies()
                session = next(c for c in cookies if c.get("name", "").startswith("archivebox_sessionid_"))
                assert session.get("domain") == admin_host and session.get("httpOnly")
                if isolated:
                    # Inspect the browser's actual cookie selection for every host family.
                    # Public replay has only the non-authorizing login hint.
                    for prefix in ("web", "api", "snap-0123456789abcdef0123456789abcdef", "example.com"):
                        host_url = f"http://{prefix}.{base_host}:{port}/"
                        selected = context.cookies([host_url])
                        assert {cookie.get("name") for cookie in selected} <= {"archivebox_admin_logged_in"}, selected
                        assert all(cookie.get("value") == "1" for cookie in selected), selected
                    # The API hostname must still reject a browser that logged in via SSO.
                    response = context.request.get(f"http://api.{base_host}:{port}/api/v1/core/snapshots")
                    assert response.status == 401, response.text()
                    # Exercise the existing private-replay handoff with the
                    # actual SSO session and a persisted private snapshot.
                    result = run_archivebox_cmd(
                        [
                            "manage",
                            "shell",
                            "-c",
                            """
import json
from django.contrib.auth import get_user_model
from archivebox.crawls.models import Crawl
from archivebox.core.models import Snapshot
from archivebox.core.routes_util import get_snapshot_host
user = get_user_model().objects.get(email='sso@example.com')
crawl = Crawl.objects.create(urls='https://private.example/', created_by=user, status=Crawl.StatusChoices.SEALED)
snapshot = Snapshot.objects.create(url='https://private.example/', crawl=crawl, config={'PERMISSIONS': 'private'}, status=Snapshot.StatusChoices.SEALED)
output = snapshot.output_dir / 'responses/private.example/index.html'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text('<p>Private SSO replay</p>')
print('REPLAY=' + json.dumps({'id': str(snapshot.id), 'host': get_snapshot_host(str(snapshot.id))}))
""",
                        ],
                        cwd=initialized_archive,
                        env=env,
                        default_cli_env=True,
                    )
                    assert result.returncode == 0, result.stderr
                    assert isinstance(result.stdout, str)
                    snapshot = json.loads(
                        next(line.removeprefix("REPLAY=") for line in result.stdout.splitlines() if line.startswith("REPLAY=")),
                    )
                    private_replay_url = f"http://{snapshot['host']}/responses/private.example/index.html?raw=1"
                    anonymous = browser.new_context()
                    response = anonymous.request.get(private_replay_url, max_redirects=0)
                    assert response.status == 302
                    anonymous.close()
                    response = context.request.get(
                        f"{origin}/admin/core/snapshot/replay-auth/?snapshot={snapshot['id']}&next=/responses/private.example/index.html?raw=1",
                    )
                    assert response.status == 200 and response.text() == "<p>Private SSO replay</p>"
                    replay_cookies = context.cookies([private_replay_url])
                    grants = [cookie for cookie in replay_cookies if cookie.get("name", "").startswith("archivebox_replay_")]
                    assert len(grants) == 1 and grants[0].get("httpOnly")
                    assert grants[0].get("domain") == urlsplit(private_replay_url).hostname
                    assert all(cookie.get("name") == "archivebox_admin_logged_in" or cookie in grants for cookie in replay_cookies)
                # Local logout requires a CSRF-protected POST; GET only asks for confirmation.
                page.goto(f"{origin}/accounts/logout/")
                page.get_by_role("button", name="Sign Out").click()
                page.goto(f"{origin}/admin/")
                assert "/admin/login/" in page.url
                if private_replay_url:
                    # The host-only grant remains in the browser, but logout
                    # revokes its authority through the server-side session.
                    response = context.request.get(private_replay_url, max_redirects=0)
                    assert response.status == 302
            if protocol == "saml":
                assert len(saml_posts) == (2 if mode == "connect" else 1)
                # A captured, valid signed assertion cannot log in a new browser session.
                replay = browser.new_context()
                replay_page = replay.new_page()
                response = replay.request.post(
                    f"{origin}/accounts/saml/keycloak/acs/",
                    data=saml_posts[0],
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                replay_page.goto(response.url)
                replay_page.goto(f"{origin}/admin/")
                assert "/admin/login/" in replay_page.url
                replay.close()
            if protocol == "saml" and mode == "open":
                # Obtain a fresh assertion from the real IdP without submitting its HTML form.
                page.goto(f"{origin}/accounts/saml/keycloak/login/")
                csrf = page.locator('input[name="csrfmiddlewaretoken"]').input_value()
                response = context.request.post(f"{origin}/accounts/saml/keycloak/login/", form={"csrfmiddlewaretoken": csrf})
                document = html.fromstring(response.text())
                fields = {tag.get("name"): tag.get("value", "") for tag in document.xpath("//input[@name]")}
                signed = base64.b64decode(fields["SAMLResponse"])
                assert b"sso@example.com" in signed
                fields["SAMLResponse"] = base64.b64encode(signed.replace(b"sso@example.com", b"forged@example.com")).decode()
                response = context.request.post(f"{origin}/accounts/saml/keycloak/acs/", form=fields)
                assert "Third-Party Login Failure" in response.text(), response.text()
                assert "Signature validation failed" in (initialized_archive / "logs/worker_uvicorn.log").read_text()
            if protocol == "oidc":
                response = context.request.get(f"{origin}/accounts/oidc/keycloak/login/callback/?code=invalid&state=wrong")
                assert "Third-Party Login Failure" in response.text(), response.text()
            context.close()
            browser.close()
        script = f"""
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(email='sso@example.com')
assert u.is_active == {mode == "open"!r}
assert u.is_staff and u.is_superuser
assert u.first_name == 'SSO' and u.last_name == 'User'
assert not u.has_usable_password()
assert SocialAccount.objects.filter(user=u).count() == 1
print('PROVIDER_OK')
"""
        if mode == "connect":
            script = """
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(email='sso@example.com')
assert u.username == 'existing' and u.has_usable_password()
assert u.is_active and u.is_superuser
assert SocialAccount.objects.filter(user=u).count() == 1
print('PROVIDER_OK')
"""
        if mode in {"closed", "collision"}:
            script = f"""
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
assert not SocialAccount.objects.exists()
assert not get_user_model().objects.filter(email='forged@example.com').exists()
assert get_user_model().objects.filter(email='sso@example.com').count() == {int(mode == "collision")}
print('PROVIDER_OK')
"""
        result = run_archivebox_cmd(["manage", "shell", "-c", script], cwd=initialized_archive, env=env, default_cli_env=True)
        assert result.returncode == 0, result.stderr
        assert isinstance(result.stdout, str) and "PROVIDER_OK" in result.stdout
    finally:
        stop_archivebox_process(proc._process)
        response = requests.delete(f"{base}/admin/realms/{realm}", headers=headers, timeout=10)
        assert response.status_code == 204, response.text
