"""Installed plugin apps contribute native routes and existing UI slots."""

import pytest
from django.urls import resolve

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def test_installed_app_owns_agent_and_importer_routes(admin_client):
    from archivebox.plugins.discovery import get_plugin_app, get_plugin_apps

    from archivebox.plugins.host import host

    app = get_plugin_app("opencode")
    assert app is not None and get_plugin_apps()["opencode"] is app
    assert get_plugin_app("wget") is None
    assert resolve("/admin/agent/").func.__module__.startswith("abx_plugins.plugins.opencode.")
    custom = resolve("/admin/importers/custom/")
    assert custom.func.__module__.startswith("abx_plugins.plugins.opencode.")
    assert resolve("/admin/agent/opencode/pty/connect").view_name in app.get_websocket_views(host)
    assert admin_client.get("/admin/importers/custom/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    response = admin_client.get("/admin/importers/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b'action="/admin/importers/custom/"' in response.content


def test_plugin_commands_are_native_cli_commands(initialized_archive):
    import json
    from archivebox.tests.conftest import run_archivebox_cmd

    help_result = run_archivebox_cmd(["plugin", "opencode", "--help"], check=True)
    assert "browser" in help_result.stdout
    assert "context" in help_result.stdout
    result = run_archivebox_cmd(["plugin", "opencode", "context", "--limit", "1"], check=True)
    context = json.loads(result.stdout)
    assert context["paths"]["collection"] == str(initialized_archive)
    assert context["limit_per_status"] == 1
    assert isinstance(context["browsers"], list)
    invalid = run_archivebox_cmd(["plugin", "opencode", "context", "--limit", "0"])
    assert invalid.returncode != 0
    assert "Traceback" not in invalid.stderr


def test_plugin_apps_use_django_app_registry():
    from django.apps import apps

    for name in ("opencode", "chrome_screencast"):
        app = apps.get_app_config(f"abx_{name}")
        assert app.name == f"abx_plugins.plugins.{name}"
        assert app.path.endswith(f"/plugins/{name}")


@pytest.mark.parametrize("app,route", [("linkhealth", "link-health"), ("storageaudit", "storage-audit"), ("storage", "storage")])
def test_removed_apps_are_not_installed_or_routed(admin_client, app, route):
    from django.apps import apps
    from django.core.management import get_commands

    assert not apps.is_installed(f"archivebox.{app}")
    assert app not in get_commands()
    assert admin_client.get(f"/admin/{route}/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 404


def test_gallery_setup_uses_plugin_command_without_starting_disabled_provider(tmp_path):
    import json
    from abx_dl.execution import iter_plugin_command
    from archivebox.plugins.discovery import get_plugin_catalog

    command = get_plugin_catalog().command("opencode", "configure-gallery")
    assert command is not None
    result = list(
        iter_plugin_command(
            command,
            stdin=[json.dumps({"model": "openai/test", "config": {"OPENCODE_ENABLED": False}, "data_dir": str(tmp_path)})],
            cwd=tmp_path,
        ),
    )
    assert [json.loads(line) for line in result] == [{"configured": False}]
    assert not (tmp_path / "opencode").exists()
