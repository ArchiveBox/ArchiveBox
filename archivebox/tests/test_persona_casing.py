"""Persona names have the same identity on case-sensitive and insensitive disks."""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing

import pytest
from django.urls import reverse

from archivebox.personas.models import Persona
from archivebox.tests.conftest import ADMIN_TEST_HOST, api_client_request, get_free_port, run_archivebox_cmd, stop_server


def test_cli_create_reuses_case_insensitive_persona(initialized_archive):
    first = run_archivebox_cmd(["persona", "create", "--permissions=private", "personal"], cwd=initialized_archive, check=True)
    second = run_archivebox_cmd(["persona", "create", "--permissions=public", "PERSONAL"], cwd=initialized_archive, check=True)
    assert json.loads(second.stdout)["id"] == json.loads(first.stdout)["id"]
    with closing(sqlite3.connect(initialized_archive / "index.sqlite3")) as db:
        rows = db.execute("SELECT name, config FROM personas_persona WHERE name != 'Default'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "personal"
    assert json.loads(rows[0][1])["PERMISSIONS"] == "private"


@pytest.mark.django_db
def test_add_form_reuses_existing_lowercase_default(admin_client, admin_user):
    original = Persona.objects.create(name="default", created_by=admin_user)
    response = admin_client.get("/add/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert list(Persona.objects.values_list("id", "name")) == [(original.id, "default")]


@pytest.mark.django_db
def test_add_form_does_not_create_personas(admin_client):
    assert not Persona.objects.exists()
    response = admin_client.get("/add/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert not Persona.objects.exists()


def test_init_creates_default_persona(initialized_archive):
    with closing(sqlite3.connect(initialized_archive / "index.sqlite3")) as db:
        assert db.execute("SELECT name FROM personas_persona").fetchall() == [("Default",)]
    assert (initialized_archive / "personas" / "Default" / "chrome_profile").is_dir()


def test_server_initializes_default_persona_for_existing_collections(initialized_archive):
    from archivebox.tests.conftest import cli_env, get_free_port, start_archivebox_server, stop_server

    # Pre-fix collections may have no persona row until the first visit to /add/.
    run_archivebox_cmd(
        ["manage", "shell", "--no-imports", "-c", "from archivebox.personas.models import Persona; Persona.objects.all().delete()"],
        cwd=initialized_archive,
        check=True,
    )
    port = get_free_port()
    try:
        start_archivebox_server(initialized_archive, port=port, env=cli_env(port=port, server=True))
        with closing(sqlite3.connect(initialized_archive / "index.sqlite3")) as db:
            assert db.execute("SELECT name FROM personas_persona").fetchall() == [("Default",)]
    finally:
        stop_server(initialized_archive)


@pytest.mark.django_db(transaction=True)
def test_admin_delete_preserves_files_and_recreation_adopts_directory_case(admin_client, admin_user):
    persona = Persona.objects.create(name="personal", created_by=admin_user)
    persona.ensure_dirs()
    profile = persona.path / "chrome_profile" / "Preferences"
    profile.write_text('{"profile":{"name":"Preserve me"}}')
    cookies = persona.path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    before = (profile.stat().st_ino, cookies.stat().st_ino)
    response = admin_client.post(reverse("admin:personas_persona_delete", args=[persona.pk]), {"post": "yes"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert not Persona.objects.filter(pk=persona.pk).exists()
    assert profile.read_text() == '{"profile":{"name":"Preserve me"}}'
    response = admin_client.post(
        reverse("admin:personas_persona_add"),
        {
            "name": "PERSONAL",
            "created_by": str(admin_user.pk),
            "permissions": "private",
            "config": "{}",
            "import_mode": "none",
            "_save": "Save",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302, response.content
    recreated = Persona.objects.get()
    assert recreated.name == "personal"
    assert recreated.path == profile.parent.parent
    assert (profile.stat().st_ino, cookies.stat().st_ino) == before


@pytest.mark.django_db(transaction=True)
def test_extension_sync_reuses_persona_case(client, api_headers):
    original = Persona.objects.create(name="personal", config={"TIMEOUT": 37})
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        payload={"extension_persona_id": "case-test", "name": "PERSONAL", "settings": {}},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content
    assert response.json()["created"] is False
    assert response.json()["persona"]["id"] == str(original.pk)
    assert Persona.objects.count() == 1
    original.refresh_from_db()
    assert original.config["TIMEOUT"] == 37


@pytest.mark.django_db(transaction=True)
def test_admin_duplicate_name_identifies_existing_record_and_directory(admin_client, admin_user):
    original = Persona.objects.create(name="personal", created_by=admin_user)
    original.ensure_dirs()
    response = admin_client.post(
        reverse("admin:personas_persona_add"),
        {
            "name": "PERSONAL",
            "created_by": str(admin_user.pk),
            "permissions": "private",
            "config": "{}",
            "import_mode": "none",
            "_save": "Save",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert str(original.pk).encode() in response.content
    assert str(original.path).encode() in response.content
    assert list(Persona.objects.values_list("id", "name")) == [(original.id, "personal")]


@pytest.mark.django_db(transaction=True)
def test_admin_case_only_edit_preserves_profile_directory(admin_client, admin_user):
    persona = Persona.objects.create(name="personal", created_by=admin_user)
    persona.ensure_dirs()
    profile = persona.path / "chrome_profile" / "Preferences"
    profile.write_text('{"profile":{"name":"Keep this profile"}}')
    inode = profile.stat().st_ino
    response = admin_client.post(
        reverse("admin:personas_persona_change", args=[persona.pk]),
        {"name": "PERSONAL", "created_by": str(admin_user.pk), "permissions": "private", "config": "{}", "_save": "Save"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302, response.content
    persona.refresh_from_db()
    assert persona.name == "personal"
    assert profile.stat().st_ino == inode
    assert profile.read_text() == '{"profile":{"name":"Keep this profile"}}'


@pytest.mark.django_db(transaction=True)
def test_extension_sync_rejects_legacy_case_conflicts_before_writing(client, api_headers):
    # Real rows representing collections created before case-insensitive matching.
    Persona.objects.bulk_create([Persona(name="personal"), Persona(name="PERSONAL")])
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        payload={"extension_persona_id": "case-test-conflict", "name": "Personal", "settings": {}, "cookies_txt": "must not be written"},
        headers=api_headers,
    )
    assert response.status_code == 409, response.content
    assert "rename" in response.content.decode().lower()
    assert "manually" in response.content.decode().lower()
    assert Persona.objects.count() == 2
    assert all(str(persona.pk).encode() in response.content for persona in Persona.objects.all())
    assert all(not (persona.path / "cookies.txt").exists() for persona in Persona.objects.all())


@pytest.fixture
def case_sensitive_collection(tmp_path):
    """Exercise actual Linux-style directory collisions, including on macOS."""
    mount = tmp_path / "case-sensitive"
    mount.mkdir()
    if sys.platform == "darwin":
        image = tmp_path / "personas.sparseimage"
        subprocess.run(
            ["hdiutil", "create", "-size", "128m", "-type", "SPARSE", "-fs", "Case-sensitive APFS", "-volname", "PersonaTest", str(image)],
            check=True,
            capture_output=True,
        )
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount), str(image)], check=True, capture_output=True)
    try:
        yield mount
    finally:
        if sys.platform == "darwin":
            subprocess.run(["hdiutil", "detach", str(mount)], check=True, capture_output=True)


def test_cli_rejects_case_conflicting_directories_without_mutating(case_sensitive_collection):
    collection = case_sensitive_collection
    run_archivebox_cmd(["init", "--quick"], cwd=collection, check=True)
    for name in ("Default", "default"):
        profile = collection / "personas" / name / "chrome_profile"
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "Preferences").write_text(name)
    commands = (["persona", "create", "Default"], ["init", "--quick"], ["server", "--daemonize", f"127.0.0.1:{get_free_port()}"])
    try:
        for command in commands:
            result = run_archivebox_cmd(command, cwd=collection)
            assert result.returncode != 0
            assert "rename" in result.stderr.lower()
            assert "manually" in result.stderr.lower()
            assert all(str(collection / "personas" / name) in result.stderr for name in ("Default", "default"))
    finally:
        stop_server(collection)
    with closing(sqlite3.connect(collection / "index.sqlite3")) as db:
        assert db.execute("SELECT name FROM personas_persona").fetchall() == [("Default",)]
    for name in ("Default", "default"):
        assert (collection / "personas" / name / "chrome_profile" / "Preferences").read_text() == name


def test_cli_adopts_existing_directory_spelling_on_case_sensitive_disk(case_sensitive_collection):
    collection = case_sensitive_collection
    run_archivebox_cmd(["init", "--quick"], cwd=collection, check=True)
    profile = collection / "personas" / "personal" / "chrome_profile" / "Preferences"
    profile.parent.mkdir(parents=True)
    profile.write_text('{"profile":{"name":"Keep me"}}')
    inode = profile.stat().st_ino
    run_archivebox_cmd(["persona", "create", "PERSONAL"], cwd=collection, check=True)
    with closing(sqlite3.connect(collection / "index.sqlite3")) as db:
        assert db.execute("SELECT name FROM personas_persona ORDER BY name").fetchall() == [("Default",), ("personal",)]
        # A legacy database can disagree with an existing directory's spelling.
        db.execute("UPDATE personas_persona SET name='PERSONAL' WHERE name='personal'")
        db.commit()
    result = run_archivebox_cmd(["persona", "create", "Personal"], cwd=collection, check=True)
    assert json.loads(result.stdout)["name"] == "personal"
    assert not (collection / "personas" / "PERSONAL").exists()
    assert profile.stat().st_ino == inode
    assert profile.read_text() == '{"profile":{"name":"Keep me"}}'
