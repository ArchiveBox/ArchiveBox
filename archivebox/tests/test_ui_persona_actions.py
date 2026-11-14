from urllib.parse import parse_qs, urlsplit

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth.models import Permission
from django.urls import reverse

from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.services.runner import CrawlRunner, run_crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST


pytestmark = pytest.mark.django_db


def test_duplicate_persona_settings_preserves_config_without_browser_identity(admin_client, admin_user):
    source = Persona.objects.create(
        name="Research",
        created_by=admin_user,
        config={
            "PERMISSIONS": "private",
            "WGET_TIMEOUT": 75,
            "WGET_WARC_ENABLED": False,
            "EXTRA_OPTIONS": {"domains": ["example.com"]},
            "OPENAI_API_KEY": "private-token",
            "COOKIES_FILE": "/private/cookies.txt",
            "AUTH_STORAGE_FILE": "/private/auth.json",
            "CHROME_USER_DATA_DIR": "/private/chrome",
            "CHROME_CDP_URL": "http://127.0.0.1:9222",
            "WGET_COOKIES_FILE": "/private/wget-cookies.txt",
        },
    )
    source.ensure_dirs()
    (source.path / "cookies.txt").write_text("private cookies")
    (source.path / "auth.json").write_text('{"cookies": []}')
    (source.path / "chrome_profile" / "Preferences").write_text("private profile")
    original_config = source.config.copy()
    url = reverse("admin:personas_persona_duplicate_settings", args=[source.pk])

    assert admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    response = admin_client.post(url, HTTP_HOST=ADMIN_TEST_HOST)
    duplicate = Persona.objects.get(name="Research copy")
    assert response.status_code == 302
    assert response.url == reverse("admin:personas_persona_change", args=[duplicate.pk])
    assert duplicate.created_by_id == admin_user.pk
    assert duplicate.config == {
        "PERMISSIONS": "private",
        "WGET_TIMEOUT": 75,
        "WGET_WARC_ENABLED": False,
        "EXTRA_OPTIONS": {"domains": ["example.com"]},
    }
    assert not duplicate.COOKIES_FILE
    assert not duplicate.AUTH_STORAGE_FILE
    assert not (duplicate.path / "chrome_profile" / "Preferences").exists()
    source.refresh_from_db()
    assert source.config == original_config
    assert (source.path / "cookies.txt").read_text() == "private cookies"
    second = admin_client.post(url, HTTP_HOST=ADMIN_TEST_HOST)
    assert second.status_code == 302
    assert Persona.objects.filter(name="Research copy 2").exists()


@pytest.mark.parametrize("permission", [None, "add_persona", "view_persona"])
def test_duplicate_requires_both_source_access_and_add_permission(client, django_user_model, admin_user, permission):
    source = Persona.objects.create(name="Protected", created_by=admin_user)
    user = django_user_model.objects.create_user(username="staff", is_staff=True)
    if permission:
        user.user_permissions.add(Permission.objects.get(content_type__app_label="personas", codename=permission))
    client.force_login(user)
    response = client.post(reverse("admin:personas_persona_duplicate_settings", args=[source.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 403
    assert Persona.objects.count() == 1


def test_duplicate_can_create_owned_settings_with_view_and_add_permissions(client, django_user_model, admin_user):
    source = Persona.objects.create(name="Shared", created_by=admin_user, config={"WGET_TIMEOUT": 70})
    user = django_user_model.objects.create_user(username="editor", is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="personas", codename__in=["add_persona", "view_persona"]))
    client.force_login(user)
    response = client.post(reverse("admin:personas_persona_duplicate_settings", args=[source.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert Persona.objects.get(name="Shared copy").created_by_id == user.pk


@pytest.mark.django_db(transaction=True)
def test_persona_test_capture_uses_add_form_and_native_crawl_results(admin_client, admin_user, recursive_test_site):
    persona = Persona.objects.create(name="Research & notes", created_by=admin_user, config={"WGET_TIMEOUT": 75, "PERMISSIONS": "private"})
    page = admin_client.get(reverse("admin:personas_persona_change", args=[persona.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    action = next(action for action in page.context["archivebox_admin_actions"] if action["label"] == "Test capture")
    assert parse_qs(urlsplit(action["url"]).query) == {"persona": [persona.name], "depth": ["0"], "max_urls": ["1"]}
    capture = admin_client.get(action["url"], HTTP_HOST=ADMIN_TEST_HOST)
    assert capture.status_code == 200
    form = capture.context["form"]
    assert form["persona"].value() == persona.name
    assert not form["url"].value()
    assert Crawl.objects.count() == 0

    response = admin_client.post(
        reverse("add"),
        {
            "url": recursive_test_site["root_url"],
            "persona": persona.name,
            "depth": "0",
            "max_urls": "1",
            "permissions": "private",
            "config": "{}",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302, response.context["form"].errors if response.context else response.content.decode()
    crawl = Crawl.objects.get()
    assert crawl.persona_id == persona.pk
    assert response.url == crawl.admin_change_url
    runner = CrawlRunner(crawl, selected_plugins=["wget"], show_progress=False)
    snapshot_ids = runner.load_run_state()
    snapshot = crawl.snapshot_set.get(pk=snapshot_ids[0])
    assert snapshot.url == recursive_test_site["root_url"]
    config = async_to_sync(runner.load_snapshot_payload)(str(snapshot.pk))["config"]
    assert config["ACTIVE_PERSONA"] == persona.name
    assert config["WGET_TIMEOUT"] == 75
    assert config["PERMISSIONS"] == "private"
    run_crawl(str(crawl.pk), selected_plugins=["wget"], show_progress=False)
    snapshot.refresh_from_db()
    assert snapshot.archiveresult_set.filter(plugin="wget", status="succeeded").exists()
    assert any("Root" in file.read_text(errors="ignore") for file in (snapshot.output_dir / "wget").rglob("*.html"))
    assert admin_client.get(response.url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
