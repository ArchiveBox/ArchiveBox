from io import StringIO

import pytest
import requests
from django.test import RequestFactory

from archivebox.api.v1_cli import ScheduleCommandSchema, cli_schedule
from archivebox.crawls.models import CrawlSchedule
from .conftest import (
    api_auth_headers,
    cli_env,
    create_admin_and_token,
    get_free_port,
    init_archive,
    start_archivebox_server,
    stop_server,
    get_http_response,
)


@pytest.mark.django_db
def test_schedule_api_creates_schedule_via_view_request(api_admin_user):
    request = RequestFactory().post("/api/v1/cli/schedule")
    request.user = api_admin_user
    setattr(request, "stdout", StringIO())
    setattr(request, "stderr", StringIO())
    args = ScheduleCommandSchema(
        every="daily",
        import_path="https://example.com/feed.xml",
        quiet=True,
    )

    response = cli_schedule(request, args)

    assert response["success"] is True
    assert response["result_format"] == "json"
    assert response["result"]["run_all_enqueued"] == 0
    assert response["result"]["run_all_maintained"] == 0
    assert CrawlSchedule.objects.count() == 1
    assert len(response["result"]["created_schedule_ids"]) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.timeout(180)
def test_api_v1_cli_schedule_creates_schedule_over_server(tmp_path, recursive_test_site):
    init_archive(tmp_path)

    port = get_free_port()
    env = cli_env(port=port, server=True)
    api_token = create_admin_and_token(tmp_path)

    try:
        start_archivebox_server(tmp_path, env=env, port=port)
        get_http_response(port, host=f"api.archivebox.localhost:{port}", path="/api/v1/docs")

        response = requests.post(
            f"http://127.0.0.1:{port}/api/v1/cli/schedule",
            headers=api_auth_headers(api_token, port=port),
            json={
                "every": "daily",
                "import_path": recursive_test_site["root_url"],
                "quiet": True,
            },
            timeout=10,
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["success"] is True
        assert payload["result_format"] == "json"
        assert len(payload["result"]["created_schedule_ids"]) == 1
    finally:
        stop_server(tmp_path)
