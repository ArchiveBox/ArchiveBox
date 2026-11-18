"""Regression coverage for the 0.9 OSINT deployment and notification workflow."""

import json
import re
import subprocess

import pytest
import requests

from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import (
    api_client_request,
    cli_env,
    create_admin_and_token,
    get_free_port,
    run_archivebox_cmd,
    run_queued_crawls,
    stop_archivebox_process,
)
from archivebox.tests.test_api_v1_cli_add import start_api_server_without_runner
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
def test_apprise_json_add_preserves_capture_options(client, api_headers):
    command = {
        "urls": ["https://example.com/changedetection"],
        "only_new": False,
        "tag": "changedetection",
        "persona": "Default",
    }
    for _ in range(2):
        response = api_client_request(
            client,
            "post",
            "/api/v1/cli/add",
            payload={"version": "1.0", "title": "Page changed", "message": json.dumps(command), "type": "info"},
            headers=api_headers,
        )
        assert response.status_code == 200, response.content
        crawl = Crawl.objects.get(pk=response.json()["result"]["crawl_id"])
        assert crawl.urls == command["urls"][0]
        assert crawl.config["ONLY_NEW"] is False
        assert crawl.tags_str == "changedetection"
    assert Crawl.objects.count() == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "message",
    [
        "Page changed",
        "[]",
        "null",
        '{"only_new": false}',
        '{"urls": 123}',
        None,
        {},
        123,
        pytest.param("[" * 2000 + "]" * 2000, id="excessive-nesting"),
    ],
)
def test_apprise_invalid_message_does_not_queue_crawl(client, api_headers, message):
    response = api_client_request(
        client,
        "post",
        "/api/v1/cli/add",
        payload={"version": "1.0", "message": message},
        headers=api_headers,
    )
    assert response.status_code == 422, response.content
    assert not Crawl.objects.exists()


def test_startup_warns_about_file_privacy_typo_without_values(initialized_archive):
    config_file = initialized_archive / "ArchiveBox.conf"
    with config_file.open("a") as config:
        config.write("\n[OSINT_TEST]\nSAVE_ARCHIVE_DOT_ORG = False\nUNRECOGNIZED_SECRET = must-not-appear\n")
    original = config_file.read_bytes()
    result = run_archivebox_cmd(["config", "--get", "ARCHIVEDOTORG_ENABLED"], cwd=initialized_archive)
    assert config_file.read_bytes() == original
    assert result.returncode == 0, result.stderr or result.stdout
    output = result.stdout + result.stderr
    assert "Traceback" not in output
    assert output.count("SAVE_ARCHIVE_DOT_ORG") == 1
    assert "ARCHIVEDOTORG_ENABLED" in output
    assert "UNRECOGNIZED_SECRET" not in output
    assert "must-not-appear" not in output
    assert "ARCHIVEDOTORG_ENABLED = false" in result.stdout
    assert "is ignored" not in output


def test_startup_accepts_environment_privacy_legacy_alias(initialized_archive):
    result = run_archivebox_cmd(
        ["config", "--get", "ARCHIVEDOTORG_ENABLED"],
        cwd=initialized_archive,
        env={"SAVE_ARCHIVE_DOT_ORG": "False"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "SAVE_ARCHIVE_DOT_ORG" in result.stderr
    assert "ARCHIVEDOTORG_ENABLED" in result.stderr
    assert "ARCHIVEDOTORG_ENABLED = false" in result.stdout
    assert "is ignored" not in result.stderr


def test_startup_accepts_supported_legacy_alias(initialized_archive):
    result = run_archivebox_cmd(
        ["config", "--get", "ARCHIVEDOTORG_ENABLED"],
        cwd=initialized_archive,
        env={"SAVE_ARCHIVEDOTORG": "False"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "ARCHIVEDOTORG_ENABLED = false" in result.stdout
    assert "SAVE_ARCHIVE_DOT_ORG" not in result.stderr


def test_startup_canonical_privacy_setting_wins_over_legacy_alias(initialized_archive):
    result = run_archivebox_cmd(
        ["config", "--get", "ARCHIVEDOTORG_ENABLED"],
        cwd=initialized_archive,
        env={"ARCHIVEDOTORG_ENABLED": "true", "SAVE_ARCHIVE_DOT_ORG": "false"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "ARCHIVEDOTORG_ENABLED = true" in result.stdout


def test_environment_legacy_privacy_opt_out_overrides_file_opt_in(initialized_archive):
    with (initialized_archive / "ArchiveBox.conf").open("a") as config:
        config.write("\n[PRIVACY_PRECEDENCE_TEST]\nARCHIVEDOTORG_ENABLED = True\n")
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "from archivebox.config.common import get_config; print('ENV_FILE_VALUE=' + str(get_config(include_machine=False).ARCHIVEDOTORG_ENABLED))",
        ],
        cwd=initialized_archive,
        env={"SAVE_ARCHIVE_DOT_ORG": "false"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "ENV_FILE_VALUE=False" in result.stdout


def test_privacy_alias_scope_and_source_reporting():
    from archivebox.config.common import _normalize_legacy_archivedotorg_config, find_config_source, normalize_runtime_config

    unchanged = {"ARCHIVEDOTORG_ENABLED": True, "UNRELATED": "preserved"}
    assert _normalize_legacy_archivedotorg_config(unchanged) is unchanged
    legacy = {"SAVE_ARCHIVE_DOT_ORG": False}
    assert _normalize_legacy_archivedotorg_config(legacy) == {"ARCHIVEDOTORG_ENABLED": False}
    assert legacy == {"SAVE_ARCHIVE_DOT_ORG": False}

    assert normalize_runtime_config({"SAVE_ARCHIVE_DOT_ORG": False}, exclude_crawl_execution=True) == {}
    assert normalize_runtime_config({"SAVE_ARCHIVE_DOT_ORG": False}, only_crawl_execution=True) == {"ARCHIVEDOTORG_ENABLED": False}
    assert (
        find_config_source(
            "ARCHIVEDOTORG_ENABLED",
            {"ARCHIVEDOTORG_ENABLED": False},
            source_inputs=(("Environment", {"SAVE_ARCHIVE_DOT_ORG": False}), ("File", {"ARCHIVEDOTORG_ENABLED": True})),
        )
        == "Environment"
    )


@pytest.mark.django_db(transaction=True)
def test_privacy_legacy_alias_in_machine_and_persona_config(initialized_archive):
    from django.contrib.auth import get_user_model

    from archivebox.config.common import get_config
    from archivebox.machine.models import Machine
    from archivebox.personas.models import Persona

    with use_archivebox_db(initialized_archive):
        user = get_user_model().objects.create_user(username="privacy-alias-regression")
        machine = Machine.current()
        machine.config = {"SAVE_ARCHIVE_DOT_ORG": False}
        machine.save(update_fields=["config"])
        assert get_config(machine=machine).ARCHIVEDOTORG_ENABLED is False
        machine.config["ARCHIVEDOTORG_ENABLED"] = True
        machine.save(update_fields=["config"])
        assert get_config(machine=machine).ARCHIVEDOTORG_ENABLED is True
        persona = Persona.objects.create(
            name="Privacy alias regression",
            created_by=user,
            config={"PERMISSIONS": "private", "SAVE_ARCHIVE_DOT_ORG": False},
        )
        assert get_config(persona=persona, include_machine=False).ARCHIVEDOTORG_ENABLED is False
        persona.config["ARCHIVEDOTORG_ENABLED"] = True
        persona.save(update_fields=["config"])
        assert get_config(persona=persona, include_machine=False).ARCHIVEDOTORG_ENABLED is True


@pytest.mark.django_db(transaction=True)
def test_direct_add_ignores_notification_fields(client, api_headers):
    response = api_client_request(
        client,
        "post",
        "/api/v1/cli/add",
        payload={"urls": ["https://example.com/direct"], "message": "not JSON"},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content
    assert Crawl.objects.get(pk=response.json()["result"]["crawl_id"]).urls == "https://example.com/direct"


@pytest.mark.django_db(transaction=True)
def test_apprise_notification_still_requires_authentication(client, api_headers):
    response = api_client_request(
        client,
        "post",
        "/api/v1/cli/add",
        payload={"message": json.dumps({"urls": ["https://example.com/unauthorized"]})},
        headers={"HTTP_HOST": api_headers["HTTP_HOST"]},
    )
    assert response.status_code == 401, response.content
    assert not Crawl.objects.exists()


def test_noninteractive_superuser_can_log_in_with_untrusted_proxy_header(initialized_archive):
    """Exercise the report's createsuperuser path through a real CSRF login."""
    username = "osint-noninteractive-admin"
    password = " OSINT-test-$-quote'93! "
    result = run_archivebox_cmd(
        ["manage", "createsuperuser", "--noinput", "--username", username, "--email", "osint@example.com"],
        cwd=initialized_archive,
        env={"DJANGO_SUPERUSER_PASSWORD": password, "IN_DOCKER": "True"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    port = get_free_port()
    env = cli_env(
        port=port,
        server=True,
        BASE_URL=f"http://127.0.0.1:{port}",
        SERVER_SECURITY_MODE="safe-onedomain-nojsreplay",
        REVERSE_PROXY_WHITELIST="",
    )
    process = start_api_server_without_runner(initialized_archive, env, port)
    try:
        with requests.Session() as session:
            url = f"http://127.0.0.1:{port}/admin/login/"
            response = session.get(url, timeout=15)
            assert response.status_code == 200
            csrf = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.text)
            assert csrf
            response = session.post(
                url,
                data={"username": username, "password": password, "csrfmiddlewaretoken": csrf[1], "next": "/admin/"},
                headers={"Remote-User": "untrusted-upstream-user"},
                allow_redirects=False,
                timeout=15,
            )
            assert response.status_code == 302, response.text
            admin = session.get(f"http://127.0.0.1:{port}/admin/", timeout=15)
            assert admin.status_code == 200
            assert username in admin.text
    finally:
        stop_archivebox_process(process)


@pytest.mark.django_db(transaction=True)
def test_real_apprise_notifications_create_distinct_saved_captures(initialized_archive, recursive_test_site):
    from archivebox.core.models import Snapshot

    port = get_free_port()
    env = cli_env(
        port=port,
        server=True,
        BASE_URL=f"http://127.0.0.1:{port}",
        SERVER_SECURITY_MODE="safe-onedomain-nojsreplay",
        PLUGINS="wget,hashes",
        WGET_ENABLED="true",
        HASHES_ENABLED="true",
        ARCHIVEDOTORG_ENABLED="false",
    )
    token = create_admin_and_token(initialized_archive)
    process = start_api_server_without_runner(initialized_archive, env, port)
    try:
        command = json.dumps(
            {
                "urls": [recursive_test_site["root_url"]],
                "only_new": False,
                "tag": "changedetection",
                "plugins": "wget,hashes",
            },
        )
        for header_prefix in ("+", "%2B"):
            result = subprocess.run(
                [
                    "uv",
                    "tool",
                    "run",
                    "--from",
                    "apprise==2.0.1",
                    "apprise",
                    "--body",
                    command,
                    f"json://127.0.0.1:{port}/api/v1/cli/add?{header_prefix}X-ArchiveBox-API-Key={token}",
                ],
                cwd=initialized_archive,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert result.returncode == 0, result.stderr + result.stdout
    finally:
        stop_archivebox_process(process)
    run_queued_crawls(initialized_archive, env=env)
    with use_archivebox_db(initialized_archive):
        snapshots = list(Snapshot.objects.filter(url=recursive_test_site["root_url"]))
        assert len(snapshots) == 2
        assert snapshots[0].id != snapshots[1].id
        assert snapshots[0].output_dir != snapshots[1].output_dir
        for snapshot in snapshots:
            assert "changedetection" in snapshot.tags.values_list("name", flat=True)
            for plugin in ("wget", "hashes"):
                assert snapshot.archiveresult_set.filter(plugin=plugin, status="succeeded").exists()
            manifest = json.loads((snapshot.output_dir / "hashes" / "hashes.json").read_text())
            assert any(row["path"].startswith("wget/") and row["size"] > 0 for row in manifest["files"])
