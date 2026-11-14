import json
import os
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from archivebox.personas.models import Persona
from archivebox.tests.conftest import (
    ADMIN_TEST_HOST,
    cli_env,
    get_free_port,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_archivebox_process,
)


COOKIE_A = "# Netscape HTTP Cookie File\n#HttpOnly_.example.com\tTRUE\t/private\tTRUE\t1900000000\tsession\tcookie-secret\n"
COOKIE_B = "other.org\tFALSE\t/\tFALSE\t0\tanonymous\tother-secret\n"
AUTH = {
    "cookies": [
        {
            "domain": ".example.com",
            "path": "/private",
            "name": "session",
            "value": "auth-secret",
            "secure": True,
            "httpOnly": True,
            "sameSite": "Strict",
            "expires": 1900000000,
        },
    ],
    "origins": [{"origin": "https://example.com", "localStorage": [{"name": "token", "value": "local-secret"}]}],
}


@pytest.mark.django_db
def test_persona_browser_state_merges_preserves_attributes_and_clears_only_selected(admin_client, admin_user):
    persona = Persona.objects.create(name="State", created_by=admin_user)
    persona.ensure_dirs()
    cookies, auth = persona.path / "cookies.txt", persona.path / "auth.json"
    cookies.write_text(COOKIE_A)
    auth.write_text(json.dumps(AUTH))
    url = reverse("admin:personas_persona_browser_state", args=[persona.pk])
    assert admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    response = admin_client.post(url, {"artifact": "cookies", "action": "merge", "payload": COOKIE_B}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200, response.content
    assert COOKIE_A.splitlines()[1] in cookies.read_text()
    assert COOKIE_B.strip() in cookies.read_text()
    assert json.loads(auth.read_text()) == AUTH
    assert all(secret not in response.content.decode() for secret in ("cookie-secret", "auth-secret", "local-secret", "other-secret"))
    incoming = {
        "cookies": [
            {
                "domain": "other.org",
                "path": "/",
                "name": "other",
                "value": "incoming-secret",
                "secure": False,
                "httpOnly": False,
                "sameSite": "Lax",
                "expires": -1,
            },
        ],
    }
    response = admin_client.post(url, {"artifact": "auth", "action": "merge", "payload": json.dumps(incoming)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200, response.content
    saved = json.loads(auth.read_text())
    assert saved["cookies"] == [*AUTH["cookies"], *incoming["cookies"]]
    assert saved["origins"] == AUTH["origins"]
    saved_cookies = cookies.read_text()
    assert admin_client.post(url, {"artifact": "auth", "action": "merge"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400
    assert json.loads(auth.read_text()) == saved
    assert admin_client.post(url, {"artifact": "cookies", "action": "clear"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    assert cookies.read_text() == ""
    assert json.loads(auth.read_text()) == saved
    cookies.write_text(saved_cookies)
    assert admin_client.post(url, {"artifact": "auth", "action": "clear"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    assert json.loads(auth.read_text()) == {}
    assert cookies.read_text() == saved_cookies


@pytest.mark.django_db
def test_persona_browser_state_is_write_only_and_requires_change_permission(client, django_user_model, admin_user):
    persona = Persona.objects.create(name="Private browser", created_by=admin_user)
    persona.ensure_dirs()
    (persona.path / "cookies.txt").write_text(COOKIE_A)
    (persona.path / "auth.json").write_text(json.dumps(AUTH))
    user = django_user_model.objects.create_user(username="state-reader", is_staff=True)
    user.user_permissions.add(Permission.objects.get(content_type__app_label="personas", codename="view_persona"))
    client.force_login(user)
    page = client.get(reverse("admin:personas_persona_change", args=[persona.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert b"example.com" in page.content
    assert b"data-state-action=" not in page.content
    assert b"cookie-secret" not in page.content and b"auth-secret" not in page.content and b"local-secret" not in page.content
    url = reverse("admin:personas_persona_browser_state", args=[persona.pk])
    assert client.post(url, {"artifact": "cookies", "action": "clear"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(admin_user)
    assert csrf_client.post(url, {"artifact": "cookies", "action": "clear"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    assert (persona.path / "cookies.txt").read_text() == COOKIE_A


@pytest.mark.django_db
def test_browser_state_rejects_invalid_import_without_overwriting_existing(admin_client, admin_user):
    persona = Persona.objects.create(name="Invalid imports", created_by=admin_user)
    persona.ensure_dirs()
    (persona.path / "cookies.txt").write_text(COOKIE_A)
    (persona.path / "auth.json").write_text(json.dumps(AUTH))
    url = reverse("admin:personas_persona_browser_state", args=[persona.pk])
    for artifact, payload in [("cookies", "bad secret payload"), ("auth", "{malformed-secret"), ("auth", '{"cookies": ["secret"]}')]:
        response = admin_client.post(url, {"artifact": artifact, "action": "merge", "payload": payload}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 400
        assert payload not in response.content.decode()
    assert (persona.path / "cookies.txt").read_text() == COOKIE_A
    assert json.loads((persona.path / "auth.json").read_text()) == AUTH


def test_persona_browser_state_controls_in_real_browser(initialized_archive, browser_runtime):
    root = initialized_archive
    port = get_free_port()
    env = cli_env(
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
        DJANGO_SUPERUSER_USERNAME="state-review",
        DJANGO_SUPERUSER_PASSWORD="local-state-password",
        DJANGO_SUPERUSER_EMAIL="state@example.com",
    )
    for command in (["manage", "createsuperuser", "--noinput"], ["persona", "create", "Browser State"]):
        result = run_archivebox_cmd(command, cwd=root, env=env, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
    persona_path = root / "personas" / "Browser State"
    (persona_path / "cookies.txt").write_text(COOKIE_A)
    (persona_path / "auth.json").write_text(json.dumps(AUTH))
    upload = root / "more-cookies.txt"
    upload.write_text(COOKIE_B)
    server = start_archivebox_server(root, port=port, env=env, log_name="browser-state-server.log")
    try:
        with sync_playwright() as playwright:
            profile = playwright.chromium.launch_persistent_context(
                str(persona_path / "chrome_profile"),
                executable_path=str(browser_runtime["chrome_binary"]),
                args=browser_runtime["chrome_args"],
            )
            profile.add_cookies(
                [
                    {
                        "name": "browser-session",
                        "value": "profile-secret",
                        "domain": "example.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "Lax",
                    },
                ],
            )
            profile.close()
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1600, "height": 1100})
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill(env["DJANGO_SUPERUSER_USERNAME"])
            page.get_by_label("Password:", exact=True).fill(env["DJANGO_SUPERUSER_PASSWORD"])
            page.get_by_role("button", name="Log in", exact=True).click()
            page.goto(base + "/admin/personas/persona/")
            page.get_by_role("link", name="Browser State", exact=True).click()
            state = page.locator(".persona-browser-state")
            expect(state).to_be_visible()
            expect(state.locator('[data-state-card="profile"] [data-state-detail]')).to_contain_text("1 cookies")
            assert all(secret not in page.content() for secret in ("cookie-secret", "auth-secret", "local-secret", "profile-secret"))
            cookies = state.locator('[data-state-card="cookies"]')
            cookies.locator("summary").click()
            cookies.locator("[data-state-file]").set_input_files(upload)
            expect(cookies.locator("[data-state-payload]")).to_have_value(COOKIE_B)
            cookies.get_by_role("button", name="Apply cookies", exact=True).click()
            expect(cookies.locator(".persona-state-message")).to_have_text("Saved.")
            expect(cookies.locator("[data-state-count]")).to_have_text("2")
            expect(cookies.locator("[data-state-payload]")).to_be_empty()
            assert COOKIE_A.splitlines()[1] in (persona_path / "cookies.txt").read_text()
            assert COOKIE_B.strip() in (persona_path / "cookies.txt").read_text()
            assert json.loads((persona_path / "auth.json").read_text()) == AUTH
            auth = state.locator('[data-state-card="auth"]')
            auth.locator("summary").click()
            auth.locator("[data-state-payload]").fill(
                json.dumps({"cookies": [{"domain": "other.org", "path": "/", "name": "other", "value": "new-secret", "sameSite": "Lax"}]}),
            )
            auth.get_by_role("button", name="Apply browser storage", exact=True).click()
            expect(auth.locator(".persona-state-message")).to_have_text("Saved.")
            assert json.loads((persona_path / "auth.json").read_text())["cookies"][0] == AUTH["cookies"][0]
            state.locator(".persona-extension-setup summary").click()
            output = Path(os.environ.get("ARCHIVEBOX_UI_SCREENSHOT_DIR", root / "screenshots"))
            output.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output / "persona-browser-state.png"), full_page=True)
            cookies.get_by_role("button", name="Clear cookies", exact=True).click()
            expect(cookies.locator(".persona-state-message")).to_have_text("Cleared.")
            assert (persona_path / "cookies.txt").read_text() == ""
            assert len(json.loads((persona_path / "auth.json").read_text())["cookies"]) == 2
            auth.get_by_role("button", name="Clear browser storage", exact=True).click()
            expect(auth.locator(".persona-state-message")).to_have_text("Cleared.")
            assert json.loads((persona_path / "auth.json").read_text()) == {}
            browser.close()
    finally:
        stop_archivebox_process(server)
