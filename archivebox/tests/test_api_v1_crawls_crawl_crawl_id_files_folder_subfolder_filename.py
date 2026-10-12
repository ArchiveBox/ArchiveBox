import pytest

from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/crawl-file-deep", created_by=api_admin_user)
    nested_dir = crawl.output_dir / "folder" / "subfolder"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "basic.txt").write_text("ok")

    response = client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/folder/subfolder/basic.txt", **api_headers)

    assert response.status_code == 200, response.content


def test_public_crawl_never_serves_persona_runtime_files(client, api_admin_user):
    from archivebox.tests.conftest import API_TEST_HOST

    crawl = Crawl.objects.create(
        urls="https://example.com/crawl-file-persona",
        created_by=api_admin_user,
        config={"PERMISSIONS": "public"},
    )
    # Crawls captured before persona runtimes moved to local TMP_DIR kept a real
    # .persona directory in the crawl output, holding the persona's logins.
    persona_dir = crawl.output_dir / ".persona" / "Default"
    persona_dir.mkdir(parents=True, exist_ok=True)
    (persona_dir / "cookies.txt").write_text(".example.com\tTRUE\t/\tTRUE\t0\tsessionid\tsecret-session-cookie\n")
    (crawl.output_dir / "chrome").mkdir(exist_ok=True)
    (crawl.output_dir / "chrome" / "cmd.sh").write_text("chrome --headless\n")

    allowed = client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/chrome/cmd.sh", HTTP_HOST=API_TEST_HOST)
    assert allowed.status_code == 200, allowed.content
    assert b"".join(allowed.streaming_content) == b"chrome --headless\n"

    for path in (".persona/Default/cookies.txt", ".PERSONA/Default/cookies.txt"):
        response = client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/{path}", HTTP_HOST=API_TEST_HOST)
        body = b"".join(response.streaming_content) if response.streaming else response.content
        assert response.status_code == 404, (path, response.status_code)
        assert b"secret-session-cookie" not in body
