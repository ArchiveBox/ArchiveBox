import pytest
import requests

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import (
    cli_env,
    create_admin_and_token,
    get_free_port,
    init_archive,
    live_api_request,
    start_archivebox_server,
    stop_archivebox_process,
    wait_for_live_api,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.timeout(180)
def test_core_api_workflow_uses_token_auth_and_persists_side_effects_over_server(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PUBLIC_INDEX="True")
    api_token = create_admin_and_token(tmp_path)

    process = start_archivebox_server(tmp_path, env=env, port=port, log_name="api-server.log")
    try:
        docs = wait_for_live_api(port)
        assert docs.status_code == 200
        openapi = wait_for_live_api(port, path="/api/v1/openapi.json")
        assert openapi.status_code == 200
        paths = openapi.json()["paths"]
        assert "/api/v1/core/snapshots" in paths
        assert "/api/v1/crawls/crawls" in paths

        unauth = requests.get(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawls",
            headers={"Host": f"api.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert unauth.status_code in (401, 403)
        bad_auth = requests.get(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawls",
            headers={"Host": f"api.archivebox.localhost:{port}", "X-ArchiveBox-API-Key": "bad-token"},
            timeout=10,
        )
        assert bad_auth.status_code in (401, 403)

        crawl_response = live_api_request(
            port,
            "post",
            "/api/v1/crawls/crawls",
            api_token=api_token,
            json={
                "urls": [recursive_test_site["root_url"]],
                "max_depth": 2,
                "tags": ["api-depth-two"],
                "label": "api crawl",
                "notes": "created through REST API",
                "config": {
                    "PLUGINS": "wget,parse_html_urls",
                    "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
                    "CRAWL_MAX_URLS": 7,
                    "CRAWL_MAX_SIZE": "0",
                    "SNAPSHOT_MAX_SIZE": "0",
                },
            },
            timeout=10,
        )
        assert crawl_response.status_code == 200, crawl_response.text
        crawl_payload = crawl_response.json()
        crawl_id = crawl_payload["id"]
        assert crawl_payload["max_depth"] == 2
        assert crawl_payload["tags_str"] == "api-depth-two"
        assert crawl_payload["config"]["PLUGINS"] == "wget,parse_html_urls"
        assert crawl_payload["config"]["CRAWL_MAX_URLS"] == 7
        pause_crawl = live_api_request(
            port,
            "patch",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            json={"action": "pause"},
            timeout=10,
        )
        assert pause_crawl.status_code == 200, pause_crawl.text
        assert pause_crawl.json()["status"] == "paused"

        snapshot_response = live_api_request(
            port,
            "post",
            "/api/v1/core/snapshots",
            api_token=api_token,
            json={
                "url": recursive_test_site["child_urls"][0],
                "crawl_id": crawl_id,
                "depth": 1,
                "title": "API child snapshot",
                "tags": ["api-child"],
                "status": "queued",
            },
            timeout=10,
        )
        assert snapshot_response.status_code == 200, snapshot_response.text
        snapshot_payload = snapshot_response.json()
        snapshot_id = snapshot_payload["id"]
        assert snapshot_payload["url"] == recursive_test_site["child_urls"][0]
        assert snapshot_payload["tags"] == ["api-child"]

        patch_snapshot = live_api_request(
            port,
            "patch",
            f"/api/v1/core/snapshot/{snapshot_id}",
            api_token=api_token,
            json={"status": "sealed", "tags": ["api-child", "api-patched"]},
            timeout=10,
        )
        assert patch_snapshot.status_code == 200, patch_snapshot.text
        assert patch_snapshot.json()["status"] == "sealed"
        assert set(patch_snapshot.json()["tags"]) == {"api-child", "api-patched"}

        tag_create = live_api_request(
            port,
            "post",
            "/api/v1/core/tags/create/",
            api_token=api_token,
            json={"name": "api-extra"},
            timeout=10,
        )
        assert tag_create.status_code == 200, tag_create.text
        tag_id = tag_create.json()["tag_id"]

        add_tag = live_api_request(
            port,
            "post",
            "/api/v1/core/tags/add-to-snapshot/",
            api_token=api_token,
            json={"snapshot_id": snapshot_id, "tag_id": tag_id},
            timeout=10,
        )
        assert add_tag.status_code == 200, add_tag.text
        remove_tag = live_api_request(
            port,
            "post",
            "/api/v1/core/tags/remove-from-snapshot/",
            api_token=api_token,
            json={"snapshot_id": snapshot_id, "tag_name": "api-extra"},
            timeout=10,
        )
        assert remove_tag.status_code == 200, remove_tag.text

        crawl_patch = live_api_request(
            port,
            "patch",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            json={"status": "sealed", "tags": ["api-sealed"]},
            timeout=10,
        )
        assert crawl_patch.status_code == 200, crawl_patch.text
        assert crawl_patch.json()["status"] == "sealed"
        assert crawl_patch.json()["tags_str"] == "api-sealed"

        snapshots_list = live_api_request(
            port,
            "get",
            "/api/v1/core/snapshots?tag=api-patched&with_archiveresults=true",
            api_token=api_token,
            timeout=10,
        )
        assert snapshots_list.status_code == 200, snapshots_list.text
        snapshot_items = snapshots_list.json()["items"]
        assert len(snapshot_items) == 1
        assert snapshot_items[0]["id"] == snapshot_id
        archiveresults = snapshot_items[0]["archiveresults"]
        assert {result["plugin"] for result in archiveresults}.issubset({"wget", "parse_html_urls"})
        assert {result["status"] for result in archiveresults}.issubset({"queued"})

        bearer_response = requests.get(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}",
            headers={"Host": f"api.archivebox.localhost:{port}", "Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        assert bearer_response.status_code == 200, bearer_response.text
        query_response = requests.get(
            f"http://127.0.0.1:{port}/api/v1/crawls/crawl/{crawl_id}?api_key={api_token}",
            headers={"Host": f"api.archivebox.localhost:{port}"},
            timeout=10,
        )
        assert query_response.status_code == 200, query_response.text

        delete_snapshot = live_api_request(
            port,
            "delete",
            f"/api/v1/core/snapshot/{snapshot_id}",
            api_token=api_token,
            timeout=10,
        )
        assert delete_snapshot.status_code == 200, delete_snapshot.text
        assert delete_snapshot.json()["success"] is True

        delete_crawl = live_api_request(
            port,
            "delete",
            f"/api/v1/crawls/crawl/{crawl_id}",
            api_token=api_token,
            timeout=10,
        )
        assert delete_crawl.status_code == 200, delete_crawl.text
        assert delete_crawl.json()["success"] is True

        with use_archivebox_db(tmp_path):
            assert Crawl.objects.filter(pk=crawl_id).count() == 0
            assert Snapshot.objects.filter(pk=snapshot_id).count() == 0
    finally:
        stop_archivebox_process(process)
