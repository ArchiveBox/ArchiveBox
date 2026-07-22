import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.test_orm_helpers import use_archivebox_db
from .conftest import (
    cli_env,
    create_admin_and_token,
    get_free_port,
    init_archive,
    live_api_request,
    start_archivebox_server,
    stop_server,
    wait_for_live_api,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.timeout(180)
def test_cli_api_add_search_update_remove_over_server(tmp_path):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True, PUBLIC_INDEX="True")
    api_token = create_admin_and_token(tmp_path)
    target_url = "https://example.com/"

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        add_response = live_api_request(
            port,
            "post",
            "/api/v1/cli/add",
            api_token=api_token,
            json={
                "urls": [target_url],
                "tag": "api-cli",
                "depth": 0,
                "parser": "url_list",
                "plugins": "parse_txt_urls,wget",
                "update": True,
                "overwrite": False,
                "index_only": True,
            },
            timeout=10,
        )
        assert add_response.status_code == 200, add_response.text
        add_payload = add_response.json()
        assert add_payload["success"] is True
        assert add_payload["result_format"] == "json"
        assert add_payload["result"]["num_snapshots"] == 0
        crawl_id = add_payload["result"]["crawl_id"]
        assert add_payload["result"]["snapshot_ids"] == []
        stop_server(tmp_path)
        from archivebox.services.runner import run_crawl

        with use_archivebox_db(tmp_path):
            run_crawl(crawl_id, show_progress=False)
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        with use_archivebox_db(tmp_path):
            snapshot = Snapshot.objects.get(crawl_id=crawl_id, url=target_url)
            snapshot_id = str(snapshot.id)
            snapshot_status = snapshot.status

        search_response = live_api_request(
            port,
            "post",
            "/api/v1/cli/search",
            api_token=api_token,
            json={
                "filter_patterns": [target_url],
                "filter_type": "exact",
                "status": snapshot_status,
                "sort": "bookmarked_at",
                "as_json": True,
                "as_html": False,
                "as_csv": "",
                "with_headers": False,
            },
            timeout=10,
        )
        assert search_response.status_code == 200, search_response.text
        search_payload = search_response.json()
        assert search_payload["success"] is True
        assert search_payload["result_format"] == "json"
        assert any(item["url"] == target_url for item in search_payload["result"])

        update_response = live_api_request(
            port,
            "post",
            "/api/v1/cli/update",
            api_token=api_token,
            json={
                "resume": None,
                "after": 0,
                "before": 4102444800,
                "filter_type": "exact",
                "filter_patterns": [target_url],
                "batch_size": 1,
                "continuous": False,
                "migrate_only": True,
            },
            timeout=20,
        )
        assert update_response.status_code == 200, update_response.text
        assert update_response.json()["success"] is True
        stop_server(tmp_path)
        start_archivebox_server(tmp_path, env=env, port=port)
        wait_for_live_api(port)

        with use_archivebox_db(tmp_path):
            crawl_obj = Crawl.objects.filter(pk=crawl_id).first()
            crawl = (crawl_obj.max_depth, crawl_obj.tags_str, crawl_obj.config) if crawl_obj else None

        assert crawl is not None
        assert crawl[0] == 0
        assert crawl[1] == "api-cli"
        assert crawl[2]["INDEX_ONLY"] is True

        remove_response = live_api_request(
            port,
            "post",
            "/api/v1/cli/remove",
            api_token=api_token,
            json={
                "delete": True,
                "after": 0,
                "before": 4102444800,
                "filter_type": "exact",
                "filter_patterns": [target_url],
            },
            timeout=20,
        )
        assert remove_response.status_code == 200, remove_response.text
        remove_payload = remove_response.json()
        assert remove_payload["success"] is True
        assert remove_payload["result"]["removed_count"] == 1
        assert snapshot_id in remove_payload["result"]["removed_snapshot_ids"]

        with use_archivebox_db(tmp_path):
            snapshot_count = Snapshot.objects.filter(pk=snapshot_id).count()

        assert snapshot_count == 0
    finally:
        stop_server(tmp_path)
