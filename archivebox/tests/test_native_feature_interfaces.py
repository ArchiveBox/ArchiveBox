"""Native folder/importer interfaces use the same persisted selection and lifecycle."""

import csv
import io
import json

import pytest

from archivebox.core.models import Folder, Snapshot
from archivebox.crawls.models import Crawl

pytestmark = pytest.mark.django_db(transaction=True)


def test_folder_api_crud_rules_and_membership(client, api_headers, api_admin_user):
    base = "/api/v1/core"
    response = client.post(f"{base}/folders", {"name": "Research"}, content_type="application/json", **api_headers)
    assert response.status_code == 200, response.content
    folder_id = response.json()["id"]
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://example.com/", title="Research article")
    response = client.patch(f"{base}/snapshot/{snapshot.pk}", {"folder_id": folder_id}, content_type="application/json", **api_headers)
    assert response.status_code == 200, response.content
    snapshot.refresh_from_db()
    assert str(snapshot.folder_id) == folder_id
    rules = {"field": "title", "lookup": "icontains", "value": "Research", "limit": 1}
    response = client.post(f"{base}/folders", {"name": "Smart", "rules": rules}, content_type="application/json", **api_headers)
    assert response.status_code == 200, response.content
    smart_id = response.json()["id"]
    response = client.get(f"{base}/snapshots", {"folder_id": smart_id}, **api_headers)
    assert response.status_code == 200, response.content
    assert [row["id"].replace("-", "") for row in response.json()["items"]] == [str(snapshot.pk)]
    assert client.get(f"{base}/folders/rules", **api_headers).json()["fields"]
    response = client.patch(
        f"{base}/folder/{smart_id}",
        {"rules": {"field": "bogus", "lookup": "exact", "value": 1}},
        content_type="application/json",
        **api_headers,
    )
    assert response.status_code == 400, response.content
    assert Folder.objects.get(pk=smart_id).rules == rules
    assert client.delete(f"{base}/folder/{folder_id}", **api_headers).status_code == 200
    snapshot.refresh_from_db()
    assert snapshot.folder_id is None
    assert client.get(f"{base}/folders").status_code == 401


@pytest.mark.parametrize("format", ["csv", "jsonl"])
def test_export_relationship_columns(client, api_headers, api_admin_user, format):
    folder = Folder.objects.create(name='Quotes, "and commas"', created_by=api_admin_user)
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://example.com/", folder=folder)
    response = client.get(f"/api/v1/core/snapshots/export/{format}", {"folder_id": str(folder.pk)}, **api_headers)
    assert response.status_code == 200, response.content
    rows = (
        list(csv.DictReader(io.StringIO(response.content.decode())))
        if format == "csv"
        else [json.loads(line) for line in response.content.splitlines()]
    )
    assert len(rows) == 1
    assert rows[0]["id"] == str(snapshot.pk)
    assert rows[0]["folder_id"] == str(folder.pk)
    assert rows[0]["folder_name"] == folder.name
    assert str(rows[0]["created_by_id"]) == str(api_admin_user.pk)


def test_importer_api_crud_and_actions(client, api_headers):
    base = "/api/v1/importers"
    response = client.get(f"{base}/catalog", **api_headers)
    assert response.status_code == 200, response.content
    assert any(item["plugin"] == "importer_rss" for item in response.json())
    data = {"plugin": "importer_rss", "feed": "feed", "name": "RSS", "settings": {"IMPORTER_RSS_URL": "https://example.com/feed.xml"}}
    response = client.post(f"{base}/sources", data, content_type="application/json", **api_headers)
    assert response.status_code == 200, response.content
    source_id = response.json()["id"]
    response = client.post(f"{base}/source/{source_id}/preview", **api_headers)
    assert response.status_code == 200, response.content
    run_id = response.json()["id"]
    assert response.json()["source_id"] == source_id
    assert client.delete(f"{base}/source/{source_id}", **api_headers).status_code == 409
    assert client.post(f"{base}/source/{source_id}/pause", **api_headers).status_code == 200
    response = client.get(f"{base}/run/{run_id}", **api_headers)
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    response = client.patch(f"{base}/source/{source_id}", {"name": "Renamed"}, content_type="application/json", **api_headers)
    assert response.status_code == 200 and response.json()["name"] == "Renamed"
    assert client.delete(f"{base}/source/{source_id}", **api_headers).status_code == 200


def test_native_cli_round_trip_and_csv(initialized_archive):
    from archivebox.tests.conftest import run_archivebox_cmd
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    def cli(*args):
        result = run_archivebox_cmd(list(args), cwd=initialized_archive, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    folder = json.loads(cli("folder", "create", 'Research, "quoted"'))
    rules = {"field": "title", "lookup": "icontains", "value": "needle"}
    smart = json.loads(cli("folder", "create", "Smart", "--rules", json.dumps(rules)))
    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(urls="https://example.com/")
        snapshot = Snapshot.objects.create(crawl=crawl, url="https://example.com/", title='needle, "quoted"', folder_id=folder["id"])
        other = Snapshot.objects.create(crawl=crawl, url="https://example.com/other", title="Unrelated")
    rows = [json.loads(line) for line in cli("list", "--folder-id", smart["id"]).splitlines()]
    assert [row["id"] for row in rows] == [str(snapshot.pk)]
    assert rows[0]["folder_name"] == folder["name"]
    rows = list(
        csv.DictReader(io.StringIO(cli("list", "--folder-id", smart["id"], "--csv", "id,title,folder_id,folder_name", "--with-headers"))),
    )
    assert rows[0]["title"] == snapshot.title and rows[0]["folder_name"] == folder["name"]
    folders = list(csv.DictReader(io.StringIO(cli("folder", "list", "--format", "csv"))))
    assert json.loads(next(row for row in folders if row["id"] == smart["id"])["rules"]) == rules
    assert json.loads(cli("folder", "move-snapshots", str(other.pk), "--destination-id", folder["id"]))["moved"] == 1
    cli("folder", "update", folder["id"], "--data", '{"name":"Renamed"}')
    cli("folder", "delete", folder["id"], "--yes")
    with use_archivebox_db(initialized_archive):
        snapshot.refresh_from_db()
        other.refresh_from_db()
        assert snapshot.folder_id is None and other.folder_id is None
    source = json.loads(
        cli(
            "importer",
            "create",
            "--plugin",
            "importer_rss",
            "--feed",
            "feed",
            "--settings",
            '{"IMPORTER_RSS_URL":"https://example.com/feed.xml"}',
        ),
    )
    cli("importer", "update", source["id"], "--data", '{"name":"My feed"}')
    run = json.loads(cli("importer", "action", source["id"], "preview"))
    assert run["source_id"] == source["id"] and run["status"] == "queued"
    cli("importer", "action", source["id"], "pause")
    run = json.loads(cli("importer", "run", run["id"]))
    assert run["status"] == "cancelled"
    rows = list(csv.DictReader(io.StringIO(cli("importer", "runs", "--source-id", source["id"], "--format", "csv"))))
    assert rows[0]["source_name"] == "My feed" and rows[0]["source_id"] == source["id"]
    cli("importer", "delete", source["id"], "--yes")


def test_importer_actions_dispatch_real_webhooks(client, api_headers):
    from archivebox.api.models import OutboundWebhook
    from archivebox.machine.models import Process

    hooks = {}
    for model, event in [("ImporterSource", "UPDATE"), ("ImporterRun", "CREATE"), ("ImporterRun", "COMPLETED")]:
        hook = OutboundWebhook(
            name=f"{model} {event}",
            ref=f"archivebox.importers.models.{model}",
            signal=event,
            actions=[{"type": "python", "code": "import sys; print(sys.stdin.read())"}],
        )
        hook.full_clean()
        hook.save()
        hooks[model, event] = hook
    source = client.post(
        "/api/v1/importers/sources",
        {"plugin": "importer_rss", "feed": "feed", "settings": {"IMPORTER_RSS_URL": "https://example.com/feed.xml"}},
        content_type="application/json",
        **api_headers,
    ).json()
    run = client.post(f"/api/v1/importers/source/{source['id']}/preview", **api_headers).json()
    response = client.post(f"/api/v1/importers/source/{source['id']}/pause", **api_headers)
    assert response.status_code == 200, response.content
    for (model, event), hook in hooks.items():
        records = Process.objects.filter(worker_type="webhook", env__ARCHIVEBOX_WEBHOOK_ID=str(hook.pk))
        payload = json.loads(records.get().stdout)
        assert payload["event"] == event
        assert payload["id"] == (source["id"] if model == "ImporterSource" else run["id"])
    # An already-paused source and already-terminal run are no-op writes.
    assert client.post(f"/api/v1/importers/source/{source['id']}/pause", **api_headers).status_code == 200
    assert Process.objects.filter(worker_type="webhook").count() == 3


def test_importer_ui_api_tables_and_private_access(admin_client, client, api_headers):
    from archivebox.tests.conftest import ADMIN_TEST_HOST, API_TEST_HOST

    data = {
        "plugin": "importer_rss",
        "feed": "feed",
        "name": 'RSS, "quoted"',
        "settings": {"IMPORTER_RSS_URL": "https://example.com/feed.xml"},
    }
    source = client.post("/api/v1/importers/sources", data, content_type="application/json", **api_headers).json()
    for http_client, url, headers in [
        (client, "/api/v1/importers/sources?format=csv", api_headers),
        (admin_client, "/admin/importers/export.csv", {"HTTP_HOST": ADMIN_TEST_HOST}),
    ]:
        response = http_client.get(url, **headers)
        assert response.status_code == 200, response.content
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        assert rows[0]["id"] == source["id"] and rows[0]["name"] == data["name"]
        assert json.loads(rows[0]["settings"]) == data["settings"]
        assert "no-store" in response["Cache-Control"]
    assert client.get("/api/v1/importers/sources?format=csv", HTTP_HOST=API_TEST_HOST).status_code == 401
    from django.test import Client

    assert Client().get("/admin/importers/export.csv", HTTP_HOST=ADMIN_TEST_HOST).status_code in {302, 403}


def test_import_to_folder_completion_payload(client, api_headers, tmp_path):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from archivebox.api.models import OutboundWebhook
    from archivebox.importers.models import ImporterRun
    from archivebox.importers.service import run_next_importer
    from archivebox.machine.models import Process
    from archivebox.services.runner import run_crawl

    site = tmp_path / "site"
    site.mkdir()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(site)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    (site / "article.html").write_text("<html><title>Folder import</title><body>Folder content.</body></html>")
    (site / "feed.xml").write_text(
        f'<rss version="2.0"><channel><title>Reading</title><item><guid>one</guid><link>{origin}/article.html</link></item></channel></rss>',
    )
    try:
        folder = client.post("/api/v1/core/folders", {"name": "Imports"}, content_type="application/json", **api_headers).json()
        source = client.post(
            "/api/v1/importers/sources",
            {"plugin": "importer_rss", "feed": "feed", "folder_id": folder["id"], "settings": {"IMPORTER_RSS_URL": f"{origin}/feed.xml"}},
            content_type="application/json",
            **api_headers,
        ).json()
        assert source["folder_name"] == "Imports", source
        hook = OutboundWebhook(
            name="Import completed",
            ref="archivebox.importers.models.ImporterRun",
            signal="COMPLETED",
            actions=[{"type": "python", "code": "import sys; print(sys.stdin.read())"}],
        )
        hook.full_clean()
        hook.save()
        run_data = client.post(f"/api/v1/importers/source/{source['id']}/import", **api_headers).json()
        assert run_next_importer(run_id=run_data["id"])
        run = ImporterRun.objects.get(pk=run_data["id"])
        assert run.status == "succeeded", run.message
        assert str(run.crawl.folder_id) == folder["id"]
        payload = json.loads(Process.objects.get(worker_type="webhook", env__ARCHIVEBOX_WEBHOOK_ID=str(hook.pk)).stdout)
        assert payload["crawl"] == str(run.crawl_id)
        run_crawl(str(run.crawl_id), selected_plugins=["title", "wget"])
        snapshot = run.crawl.snapshot_set.get()
        assert str(snapshot.folder_id) == folder["id"]
        assert snapshot.archiveresult_set.filter(plugin="wget", status="succeeded").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_folder_and_importer_ui_downloads(live_server, admin_user, browser_runtime, tmp_path, settings):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from archivebox.importers.models import ImporterSource

    folder = Folder.objects.create(name="UI exports", created_by=admin_user)
    origin = f"http://admin.archivebox.localhost:{urlsplit(live_server.url).port}"
    from archivebox.machine.models import Machine

    base_url = origin.replace("//admin.archivebox", "//archivebox")
    settings.CONFIG = settings.CONFIG.model_copy(update={"BASE_URL": base_url})
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base_url}
    machine.save(update_fields=["config"])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(f"{origin}/admin/login/?next=/admin/importers/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        assert page.goto(f"{origin}/admin/importers/new/importer_rss/feed/").status == 200
        page.locator('[name="setting_IMPORTER_RSS_URL"]').fill("https://example.com/feed.xml")
        page.get_by_text("Advanced options", exact=True).click()
        page.locator('[name="name"]').fill("UI feed")
        page.locator('[name="folder"]').select_option(str(folder.pk))
        page.get_by_role("button", name="Save importer", exact=True).click()
        expect(page.get_by_role("link", name="UI exports", exact=True)).to_be_visible()
        assert page.goto(f"{origin}/admin/importers/").status == 200
        with page.expect_download() as download:
            page.get_by_role("link", name="CSV", exact=True).click()
        path = tmp_path / "importers.csv"
        download.value.save_as(path)
        rows = list(csv.DictReader(path.open()))
        assert rows[0]["folder_id"] == str(folder.pk) and rows[0]["name"] == "UI feed"
        assert page.goto(f"{origin}/admin/core/folder/").status == 200
        with page.expect_download() as download:
            page.get_by_role("link", name="JSONL", exact=True).click()
        path = tmp_path / "folders.jsonl"
        download.value.save_as(path)
        assert json.loads(path.read_text().splitlines()[0])["id"] == str(folder.pk)
        browser.close()
    source = ImporterSource.objects.get(name="UI feed")
    assert source.folder_id == folder.pk


def test_mcp_folder_and_importer_actions(initialized_archive):
    from archivebox.tests.conftest import run_archivebox_cmd

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "folder", "arguments": {"action": "create", "name": "MCP folder"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "importer",
                "arguments": {
                    "action": "create",
                    "plugin": "importer_rss",
                    "feed": "feed",
                    "settings": '{"IMPORTER_RSS_URL":"https://example.com/rss"}',
                },
            },
        },
    ]
    result = run_archivebox_cmd(["mcp"], cwd=initialized_archive, input="".join(json.dumps(item) + "\n" for item in requests), timeout=30)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    tools = {tool["name"]: tool for tool in responses[0]["result"]["tools"]}
    assert tools["importer"]["inputSchema"]["properties"]["operation"]["enum"] == [
        "check",
        "preview",
        "import",
        "pause",
        "resume",
        "reset",
        "reset_code",
    ]
    assert not responses[1]["result"]["isError"], responses[1]
    assert not responses[2]["result"]["isError"], responses[2]
    source = responses[2]["result"]["structuredContent"]["records"][0]
    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "importer", "arguments": {"action": "action", "source_id": source["id"], "operation": "preview"}},
    }
    result = run_archivebox_cmd(["mcp"], cwd=initialized_archive, input=json.dumps(request) + "\n", timeout=30)
    response = json.loads(result.stdout)["result"]
    assert not response["isError"], response
    assert response["structuredContent"]["records"][0]["status"] == "queued"


def test_native_api_schema_and_migration_state(client, api_headers):
    from django.core.management import call_command

    call_command("makemigrations", "importers", check=True, dry_run=True, verbosity=0)
    response = client.get("/api/v1/openapi.json", **api_headers)
    assert response.status_code == 200, response.content
    schema = response.json()
    assert set(schema["paths"]["/api/v1/core/folder/{folder_id}"]) == {"get", "patch", "delete"}
    assert set(schema["paths"]["/api/v1/importers/source/{source_id}"]) == {"get", "patch", "delete"}
    assert "rules" in schema["components"]["schemas"]["FolderSchema"]["properties"]
    assert "folder_id" in schema["components"]["schemas"]["SourceSchema"]["properties"]
    assert "source_id" in schema["components"]["schemas"]["RunSchema"]["properties"]


def test_invalid_snapshot_update_does_not_move_folder(client, api_headers):
    folder = Folder.objects.create(name="Destination")
    crawl = Crawl.objects.create(urls="https://example.com/")
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://example.com/")
    response = client.patch(
        f"/api/v1/core/snapshot/{snapshot.pk}",
        {"folder_id": str(folder.pk), "status": "invalid"},
        content_type="application/json",
        **api_headers,
    )
    assert response.status_code == 400
    snapshot.refresh_from_db()
    assert snapshot.folder_id is None


def test_referenced_folder_deletion_preserves_rules_and_membership(client, admin_client, api_headers):
    from archivebox.tests.conftest import ADMIN_TEST_HOST

    target = Folder.objects.create(name="Referenced")
    saved = Folder.objects.create(name="Saved selection", rules={"field": "folder", "lookup": "in_folder", "value": str(target.pk)})
    crawl = Crawl.objects.create(urls="https://example.com/")
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://example.com/", folder=target)
    response = client.delete(f"/api/v1/core/folder/{target.pk}", **api_headers)
    assert response.status_code == 400, response.content
    response = admin_client.post("/admin/core/folder/remove/", {"folder_id": str(target.pk)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 400, response.content
    snapshot.refresh_from_db()
    assert snapshot.folder_id == target.pk
    assert Snapshot.objects.in_folder(saved.pk).get().pk == snapshot.pk
