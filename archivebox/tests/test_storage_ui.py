"""Real storage forms and rclone transfers, without cloud credentials."""

from pathlib import Path

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def test_storage_local_config_and_real_connection_check(admin_client, tmp_path):
    from archivebox.storage.models import StorageDestination, StorageRun
    from archivebox.storage.service import config_path, run_next

    destination_dir = tmp_path.parent / (tmp_path.name + "-archive-copies")
    destination_dir.mkdir()
    response = admin_client.post(
        "/admin/storage/new/",
        {
            "name": "External disk",
            "provider": "local",
            "path": str(destination_dir),
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302, response.context["form"].errors if response.context else response.content
    destination = StorageDestination.objects.get(name="External disk")
    assert config_path(destination).stat().st_mode & 0o077 == 0
    response = admin_client.post(f"/admin/storage/{destination.pk}/check/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    pending = admin_client.get(f"/admin/storage/{destination.pk}/", HTTP_HOST=ADMIN_TEST_HOST)
    assert b"Operation in progress" in pending.content
    assert b"disabled>Check connection</button>" in pending.content
    assert b"disabled>Copy sealed snapshots</button>" in pending.content
    assert b"Cancel operation" in pending.content
    assert run_next()
    run = StorageRun.objects.get(destination=destination)
    assert run.status == "succeeded", run.message
    assert list(destination_dir.iterdir()) == []
    response = admin_client.get(f"/admin/storage/{destination.pk}/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"Connection verified" in response.content


def test_storage_credentials_are_private_and_never_rendered(admin_client):
    from archivebox.storage.models import StorageDestination
    from archivebox.storage.service import config_path

    secret = "a-private-s3-secret-not-for-html"
    response = admin_client.post(
        "/admin/storage/new/",
        {
            "name": "S3 archive",
            "provider": "s3",
            "path": "my-bucket/archivebox",
            "s3_provider": "AWS",
            "region": "us-east-1",
            "access_key_id": "TESTKEY",
            "secret_access_key": secret,
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302, response.context["form"].errors if response.context else response.content
    destination = StorageDestination.objects.get(name="S3 archive")
    assert secret in config_path(destination).read_text()
    assert config_path(destination).stat().st_mode & 0o077 == 0
    for path in ("/admin/storage/", f"/admin/storage/{destination.pk}/", f"/admin/storage/{destination.pk}/edit/"):
        response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert secret.encode() not in response.content
    assert secret not in str(destination.__dict__)


def test_storage_rejects_recursive_destination(admin_client):
    from archivebox.config.constants import CONSTANTS

    response = admin_client.post(
        "/admin/storage/new/",
        {
            "name": "Unsafe",
            "provider": "local",
            "path": str(CONSTANTS.ARCHIVE_DIR / "copies"),
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert b"outside the collection" in response.content


def test_storage_requires_superuser(client):
    response = client.get("/admin/storage/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302 and "/login/" in response["Location"]


def test_storage_oauth_rejects_forged_or_missing_state(admin_client):
    response = admin_client.get("/admin/storage/oauth/callback/?state=forged&code=untrusted", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 403


def test_storage_edit_preserves_saved_credentials_and_blocks_active_job(admin_client):
    from archivebox.storage.models import StorageDestination
    from archivebox.storage.service import read_options

    settings = {
        "name": "S3 archive",
        "provider": "s3",
        "path": "bucket/prefix",
        "s3_provider": "AWS",
        "region": "us-east-1",
        "access_key_id": "KEY",
        "secret_access_key": "private-key-for-storage-test",
    }
    assert admin_client.post("/admin/storage/new/", settings, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    destination = StorageDestination.objects.get(name="S3 archive")
    settings.update(name="Renamed", secret_access_key="")
    assert admin_client.post(f"/admin/storage/{destination.pk}/edit/", settings, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    destination.refresh_from_db()
    assert read_options(destination)["secret_access_key"] == "private-key-for-storage-test"
    assert admin_client.post(f"/admin/storage/{destination.pk}/check/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    settings["name"] = "Must not change"
    response = admin_client.post(f"/admin/storage/{destination.pk}/edit/", settings, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"Wait for the active storage operation" in response.content
    destination.refresh_from_db()
    assert destination.name == "Renamed"


def test_storage_oauth_start_uses_registered_callback_and_private_session(admin_client):
    from urllib.parse import parse_qs, urlparse
    from archivebox.storage.models import StorageDestination

    assert (
        admin_client.post(
            "/admin/storage/new/",
            {
                "name": "Google Drive",
                "provider": "drive",
                "path": "ArchiveBox",
                "drive_auth": "oauth",
                "client_id": "test-client.apps.googleusercontent.com",
                "client_secret": "private-client-secret",
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        ).status_code
        == 302
    )
    destination = StorageDestination.objects.get(name="Google Drive")
    response = admin_client.post(f"/admin/storage/{destination.pk}/connect/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    authorization = urlparse(response["Location"])
    assert authorization.scheme == "https" and authorization.netloc == "accounts.google.com"
    query = parse_qs(authorization.query)
    assert query["redirect_uri"] == [f"http://{ADMIN_TEST_HOST}/admin/storage/oauth/callback/"]
    assert query["access_type"] == ["offline"]
    assert query["state"][0] == admin_client.session["storage_oauth"]["state"]
    assert "private-client-secret" not in response["Location"]


def test_storage_jobs_keep_their_destination_and_credential_revision(admin_client, tmp_path):
    from archivebox.storage.models import StorageDestination, StorageRun
    from archivebox.storage.service import config_path, run_next

    original_path = tmp_path.parent / (tmp_path.name + "-original")
    revised_path = tmp_path.parent / (tmp_path.name + "-revised")
    settings = {"name": "Versioned storage", "provider": "local", "path": str(original_path)}
    assert admin_client.post("/admin/storage/new/", settings, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    destination = StorageDestination.objects.get(name="Versioned storage")
    old_config = config_path(destination)
    assert admin_client.post(f"/admin/storage/{destination.pk}/check/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    run = StorageRun.objects.get(destination=destination)
    assert run.destination_path == str(original_path)
    assert run.config_revision == destination.config_revision
    assert run_next()
    run.refresh_from_db()
    assert run.status == "succeeded", run.message
    settings["path"] = str(revised_path)
    assert admin_client.post(f"/admin/storage/{destination.pk}/edit/", settings, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    destination.refresh_from_db()
    run.refresh_from_db()
    assert run.destination_path == str(original_path)
    assert run.config_revision != destination.config_revision
    assert old_config.exists() and old_config != config_path(destination)
    assert old_config.stat().st_mode & 0o077 == 0
    assert destination.checked_at is None


def test_storage_copies_sealed_snapshot_files(admin_client, admin_user, tmp_path):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.storage.models import StorageDestination, StorageRun
    from archivebox.storage.service import run_next

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    output = Path(snapshot.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    # Ordinary filesystem payload; browser capture evidence is collected separately.
    (output / "article.txt").write_text("A real file copied by rclone.\n")
    snapshot.seal()
    destination_dir = tmp_path.parent / (tmp_path.name + "-copies")
    destination_dir.mkdir()
    assert (
        admin_client.post(
            "/admin/storage/new/",
            {
                "name": "Archive copies",
                "provider": "local",
                "path": str(destination_dir),
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        ).status_code
        == 302
    )
    destination = StorageDestination.objects.get(name="Archive copies")
    assert admin_client.post(f"/admin/storage/{destination.pk}/copy/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next()
    run = StorageRun.objects.get(destination=destination)
    assert run.status == "succeeded", run.message
    assert run.copied_snapshots == 1
    files = list(destination_dir.rglob("article.txt"))
    assert len(files) == 1
    assert files[0].read_bytes() == (output / "article.txt").read_bytes()
    assert (output / "article.txt").exists()
