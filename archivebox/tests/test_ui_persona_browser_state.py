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
    partial = {"cookies": [{"domain": ".example.com", "path": "/private", "name": "session", "value": "changed-secret", "secure": False}]}
    response = admin_client.post(url, {"artifact": "auth", "action": "merge", "payload": json.dumps(partial)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    saved = json.loads(auth.read_text())
    assert saved["cookies"][0] == {**AUTH["cookies"][0], "value": "changed-secret", "secure": False}
    assert saved["cookies"][1] == incoming["cookies"][0]
    saved_cookies = cookies.read_text()
    assert admin_client.post(url, {"artifact": "auth", "action": "merge"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400
    assert json.loads(auth.read_text()) == saved
    assert admin_client.post(url, {"artifact": "cookies", "action": "clear"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    assert cookies.read_text() == ""
    assert json.loads(auth.read_text()) == saved
    cookies.write_text(saved_cookies)
    assert admin_client.post(url, {"artifact": "auth", "action": "clear"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    assert json.loads(auth.read_text()) == {"cookies": [], "origins": []}
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


def test_persona_browser_state_controls_in_real_browser(initialized_archive, browser_runtime, recursive_test_site):
    from urllib.parse import urlsplit

    root = initialized_archive
    port = get_free_port()
    origin = recursive_test_site["root_url"].rstrip("/")
    local_domain = urlsplit(origin).hostname
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
    incoming_cookies = (
        COOKIE_A.replace("cookie-secret", "pasted-secret") + COOKIE_B + f"{local_domain}\tFALSE\t/\tFALSE\t0\tlocal\tlocal-cookie-secret\n"
    )
    upload = root / "more-cookies.txt"
    upload.write_text(incoming_cookies)
    server = start_archivebox_server(root, port=port, env=env, log_name="browser-state-server.log")
    try:
        with sync_playwright() as playwright:
            launch = {"executable_path": str(browser_runtime["chrome_binary"]), "args": browser_runtime["chrome_args"]}
            # Keep the browser-profile command's field trials; Playwright's
            # override makes its imported IndexedDB invisible on reopen.
            profile_launch = {**launch, "ignore_default_args": ["--disable-field-trial-config"]}
            profile = playwright.chromium.launch_persistent_context(str(persona_path / "chrome_profile"), **profile_launch)
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
                        "expires": 1900000000,
                    },
                ],
            )
            stored_page = profile.new_page()
            stored_page.goto(origin)
            stored_page.evaluate("localStorage.setItem('keep', 'profile-only-secret')")
            profile.close()
            browser = playwright.chromium.launch(**launch)
            page = browser.new_page(viewport={"width": 1600, "height": 1100})
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill(env["DJANGO_SUPERUSER_USERNAME"])
            page.get_by_label("Password:", exact=True).fill(env["DJANGO_SUPERUSER_PASSWORD"])
            page.get_by_role("button", name="Log in", exact=True).click()
            page.goto(base + "/admin/personas/persona/")
            with page.expect_response(lambda response: response.url.endswith("/browser-state/")) as inspected:
                page.get_by_role("link", name="Browser State", exact=True).click()
            assert inspected.value.ok, inspected.value.text()
            assert inspected.value.json()["state"]["inventory_complete"] is True
            state = page.locator(".persona-browser-state")
            expect(state.locator("[data-state-total]")).to_have_text("2")
            expect(state.locator(".persona-state-heading")).to_have_css("color", "rgb(52, 64, 84)")
            expect(state.locator("[data-state-status]")).to_be_empty()
            expect(state.locator(f'[data-state-domain="{local_domain}"]')).to_be_visible()
            expect(state.locator(".persona-profile-path")).to_contain_text(str(persona_path / "chrome_profile"))
            assert state.locator("[data-profile-version]").inner_text() != "—"
            assert all(
                secret not in page.content()
                for secret in ("cookie-secret", "auth-secret", "local-secret", "profile-secret", "profile-only-secret")
            )
            expect(page.locator(".persona-card-config .field-config")).to_be_visible()
            expect(page.locator(".persona-card-timestamps .fieldBox.field-id")).to_be_visible()
            expect(page.locator(".persona-card-timestamps .form-multiline")).to_have_css("display", "flex")
            state.get_by_role("searchbox", name="Filter browser-state sites").fill("other")
            expect(state.locator("[data-state-empty]")).to_have_text("No matching sites")
            state.get_by_role("searchbox", name="Filter browser-state sites").fill("")
            state.get_by_role("button", name="Add browser state").click()
            state.locator("[data-state-file]").set_input_files(upload)
            expect(state.locator("[data-state-payload]")).to_have_value(incoming_cookies)
            state.get_by_role("button", name="Apply browser state").click()
            expect(state.locator("[data-state-status]")).to_have_text("Saved.")
            expect(state.locator("[data-state-total]")).to_have_text("3")
            assert COOKIE_B.strip() in (persona_path / "cookies.txt").read_text()
            updated_cookie = json.loads((persona_path / "auth.json").read_text())["cookies"][0]
            assert updated_cookie == {**AUTH["cookies"][0], "value": "pasted-secret"}
            incoming_auth = {
                "cookies": [
                    {
                        "domain": local_domain,
                        "path": "/",
                        "name": "local",
                        "value": "updated-local-secret",
                        "sameSite": "Lax",
                        "expires": 1900000000,
                    },
                ],
                "origins": [
                    {
                        "origin": origin,
                        "localStorage": [{"name": "added", "value": "local-added-secret"}],
                        "sessionStorage": [{"name": "session", "value": "session-secret"}],
                        "indexedDB": [
                            {
                                "name": "Notes",
                                "version": 1,
                                "stores": [
                                    {
                                        "name": "entries",
                                        "keyPath": "id",
                                        "autoIncrement": False,
                                        "indexes": [],
                                        "records": [{"value": {"id": 1, "secret": "indexed-secret"}}],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            }
            state.get_by_role("button", name="Add browser state").click()
            state.locator("[data-state-payload]").fill(json.dumps(incoming_auth))
            with page.expect_response(lambda response: response.url.endswith("/browser-state/")) as import_response:
                state.get_by_role("button", name="Apply browser state").click()
            assert import_response.value.json()["profile_synced"] is True, import_response.value.json()
            expect(state.locator("[data-state-status]")).to_have_text("Saved.")
            saved_auth = json.loads((persona_path / "auth.json").read_text())
            assert saved_auth["origins"][0] == AUTH["origins"][0]
            assert saved_auth["origins"][1] == incoming_auth["origins"][0]
            output = Path(os.environ.get("ARCHIVEBOX_UI_SCREENSHOT_DIR", root / "screenshots"))
            output.mkdir(parents=True, exist_ok=True)
            state.locator(".persona-extension-setup summary").click()
            page.screenshot(path=str(output / "persona-browser-state.png"), full_page=True)
            profile = playwright.chromium.launch_persistent_context(str(persona_path / "chrome_profile"), **profile_launch)
            imported = {(cookie["domain"], cookie["name"]): cookie for cookie in profile.cookies()}
            assert imported[(".example.com", "session")]["value"] == "pasted-secret"
            assert imported[(".example.com", "session")]["sameSite"] == "Strict"
            assert imported[("example.com", "browser-session")]["value"] == "profile-secret"
            assert imported[(local_domain, "local")]["value"] == "updated-local-secret"
            stored_page = profile.new_page()
            stored_page.goto(origin)
            assert stored_page.evaluate('localStorage.getItem("keep")') == "profile-only-secret"
            assert stored_page.evaluate('localStorage.getItem("added")') == "local-added-secret"
            record = stored_page.evaluate(
                """() => new Promise((resolve,reject) => { const request=indexedDB.open('Notes');request.onerror=()=>reject(request.error);request.onsuccess=()=>{const db=request.result;try { const read=db.transaction('entries').objectStore('entries').get(1);read.onerror=()=>reject(read.error);read.onsuccess=()=>{resolve(read.result);db.close();}; } catch(error) { db.close();reject(error); }};})""",
            )
            assert record == {"id": 1, "secret": "indexed-secret"}
            profile.close()
            state.get_by_role("button", name=f"Remove {local_domain}", exact=True).click()
            expect(state.locator("[data-state-status]")).to_have_text("Site removed.")
            expect(state.locator("[data-state-total]")).to_have_text("2")
            expect(state.locator(f'[data-state-domain="{local_domain}"]')).to_have_count(0)
            remaining = json.loads((persona_path / "auth.json").read_text())
            assert remaining["origins"] == AUTH["origins"]
            assert all(cookie["domain"] != local_domain for cookie in remaining["cookies"])
            assert local_domain not in (persona_path / "cookies.txt").read_text()
            assert COOKIE_B.strip() in (persona_path / "cookies.txt").read_text()
            profile = playwright.chromium.launch_persistent_context(str(persona_path / "chrome_profile"), **profile_launch)
            assert all(cookie["domain"].lstrip(".") != local_domain for cookie in profile.cookies())
            assert any(cookie["value"] == "profile-secret" for cookie in profile.cookies())
            stored_page = profile.new_page()
            stored_page.goto(origin)
            assert stored_page.evaluate("localStorage.length") == 0
            assert stored_page.evaluate("indexedDB.databases()") == []
            page.screenshot(path=str(output / "persona-browser-state-removed.png"), full_page=True)
            state.get_by_role("button", name="Add browser state").click()
            state.locator("[data-state-payload]").fill(COOKIE_B.replace("other-secret", "saved-while-locked"))
            state.get_by_role("button", name="Apply browser state").click()
            expect(state.locator("[data-state-status]")).to_have_text("Saved. Chrome sync unavailable.")
            assert "saved-while-locked" in (persona_path / "cookies.txt").read_text()
            assert json.loads((persona_path / "auth.json").read_text()) == remaining
            assert any(cookie["value"] == "profile-secret" for cookie in profile.cookies())
            profile.close()
            browser.close()
    finally:
        stop_archivebox_process(server)


def test_auth_merge_preserves_omitted_storage_and_encoded_indexeddb_records(tmp_path):
    from archivebox.personas.importers import _merge_auth_storage

    existing = tmp_path / "auth.json"
    incoming = tmp_path / "incoming.json"
    encoded_a = {"valueEncoded": {"o": [{"k": "id", "v": 1}]}}
    encoded_b = {"valueEncoded": {"o": [{"k": "id", "v": 2}]}}
    keyed = {"keyEncoded": "identity", "valueEncoded": {"o": [{"k": "value", "v": "old"}]}}
    native = {"name": "Notes", "version": 1, "stores": [{"name": "entries", "keyPath": "id", "records": [encoded_a, keyed]}]}
    dexie_payload = {
        "formatName": "dexie",
        "formatVersion": 1,
        "data": {
            "databaseName": "Notes",
            "tables": [],
            "data": [{"tableName": "entries", "inbound": True, "rows": [{"id": 1, "keep": True}]}],
        },
    }
    dexie = {"name": "Notes", "version": 1, "stores": [{"name": "entries", "keyPath": "id"}], "data": json.dumps(dexie_payload)}
    existing.write_text(
        json.dumps(
            {
                "localStorage": {"https://example.com": {"keep": "old", "replace": "old"}},
                "sessionStorage": {"https://example.com": {"keep": "session"}},
                "origins": [
                    {
                        "origin": "https://example.com",
                        "localStorage": [{"name": "keep", "value": "old"}],
                        "sessionStorage": [{"name": "session", "value": "old"}],
                        "indexedDB": [native, dexie],
                    },
                ],
            },
        ),
    )
    replacement = {"keyEncoded": keyed["keyEncoded"], "valueEncoded": {"o": [{"k": "value", "v": "new"}]}}
    incoming.write_text(
        json.dumps(
            {
                "localStorage": {"https://example.com": {"replace": "new"}},
                "origins": [
                    {
                        "origin": "https://example.com",
                        "localStorage": [{"name": "add", "value": "new"}],
                        "indexedDB": [
                            {
                                **native,
                                "stores": [
                                    {"name": "entries", "records": [encoded_b, replacement]},
                                    {
                                        "name": "compound",
                                        "keyPathArray": ["one", "two"],
                                        "records": [{"value": {"one": 1, "two": 2}}, {"value": {"one": 2, "two": 3}}, encoded_a, encoded_b],
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
        ),
    )
    _merge_auth_storage(existing, incoming)
    result = json.loads(existing.read_text())
    assert result["localStorage"]["https://example.com"] == {"keep": "old", "replace": "new"}
    assert result["sessionStorage"]["https://example.com"] == {"keep": "session"}
    origin = result["origins"][0]
    assert origin["localStorage"] == [
        {"name": "keep", "value": "old"},
        {"name": "replace", "value": "new"},
        {"name": "add", "value": "new"},
    ]
    assert origin["sessionStorage"] == [{"name": "session", "value": "old"}]
    assert origin["indexedDB"][0] == dexie
    assert "data" not in origin["indexedDB"][1]
    stores = origin["indexedDB"][1]["stores"]
    assert stores[0]["records"] == [encoded_a, replacement, encoded_b]
    assert stores[1]["records"] == [{"value": {"one": 1, "two": 2}}, {"value": {"one": 2, "two": 3}}, encoded_a, encoded_b]
    from archivebox.personas.state_forms import validate_auth

    validate_auth(existing.read_text())
    incoming.write_text(
        json.dumps(
            {
                "origins": [
                    {
                        "origin": "https://example.com",
                        "indexedDB": [
                            {
                                **dexie,
                                "data": json.dumps(
                                    {
                                        **dexie_payload,
                                        "data": {
                                            **dexie_payload["data"],
                                            "data": [{"tableName": "entries", "inbound": True, "rows": [{"id": 2, "add": True}]}],
                                        },
                                    },
                                ),
                            },
                        ],
                    },
                ],
            },
        ),
    )
    _merge_auth_storage(existing, incoming)
    databases = json.loads(existing.read_text())["origins"][0]["indexedDB"]
    assert databases[0] == origin["indexedDB"][1]
    assert json.loads(databases[1]["data"])["data"]["data"][0]["rows"] == [{"id": 1, "keep": True}, {"id": 2, "add": True}]
