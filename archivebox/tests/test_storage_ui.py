"""Native primary-storage configuration, private credentials, and fail-closed I/O."""

import subprocess
import sys
import time

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def test_storage_connection_is_native_config_and_credentials_are_private(admin_client, tmp_path):
    from archivebox.storage.service import config_path, read_config, settings
    from archivebox.machine.models import Machine

    secret = "private-input-not-for-output"
    response = admin_client.post(
        "/admin/storage/configure/",
        {
            "provider": "s3",
            "path": "bucket/archive",
            "s3_provider": "AWS",
            "region": "us-east-1",
            "access_key_id": "key-for-form-validation",
            "secret_access_key": secret,
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    metadata, options = read_config()
    assert metadata == {"provider": "s3", "path": "bucket/archive"}
    assert options["secret_access_key"] == secret
    assert config_path().stat().st_mode & 0o077 == 0
    assert secret not in str(Machine.current_readonly().config)
    assert not settings().get("ARCHIVE_STORAGE_ACTIVE")
    # Older private configs may contain a name. It is never a separate archive
    # and must not turn into a content-specific heading or editable name field.
    from archivebox.storage.service import write_config

    write_config({**metadata, "name": "Retired custom archive name"}, options)
    for path in ("/admin/storage/", "/admin/storage/configure/"):
        response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200 and secret.encode() not in response.content
        assert response.get("Referrer-Policy") != "no-referrer"
        assert b"id_name" not in response.content
        assert b"Retired custom archive name" not in response.content


def test_storage_rejects_recursive_destination_and_requires_superuser(admin_client):
    from django.test import Client
    from archivebox.config.constants import CONSTANTS

    response = admin_client.post(
        "/admin/storage/configure/",
        {
            "provider": "local",
            "path": str(CONSTANTS.ARCHIVE_DIR / "nested"),
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200 and b"outside the collection" in response.content
    response = Client().get("/admin/storage/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302 and "/login/" in response["Location"]
    response = admin_client.get("/admin/storage/oauth/callback/?state=forged&code=untrusted", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 403


@pytest.mark.parametrize("path", ["relative/archive", "~archivebox-user-that-does-not-exist/archive"])
def test_storage_local_destination_requires_explicit_absolute_path(admin_client, path):
    from archivebox.storage.service import settings

    response = admin_client.post(
        "/admin/storage/configure/",
        {"provider": "local", "path": path},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert "path" in response.context["form"].errors
    assert not settings().get("ARCHIVE_STORAGE_REVISION")


def test_storage_saves_the_validated_local_destination(admin_client, tmp_path_factory):
    from archivebox.config.constants import CONSTANTS
    from archivebox.storage.service import read_config, settings

    external = tmp_path_factory.mktemp("external-storage")
    destination = external / "archive disk"
    destination.mkdir()
    alias = external / "storage-alias"
    alias.symlink_to(destination, target_is_directory=True)
    response = admin_client.post(
        "/admin/storage/configure/",
        {"provider": "local", "path": str(alias / "new archive")},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    metadata, options = read_config()
    assert metadata == {"provider": "local", "path": str(destination.resolve() / "new archive")}
    assert options == {"type": "local"}
    assert not (destination / "new archive").exists()
    revision = settings()["ARCHIVE_STORAGE_REVISION"]
    alias.unlink()
    alias.symlink_to(CONSTANTS.DATA_DIR, target_is_directory=True)
    for invalid_path in (alias / "nested", CONSTANTS.DATA_DIR.parent):
        response = admin_client.post(
            "/admin/storage/configure/",
            {"provider": "local", "path": str(invalid_path)},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 200
        assert "path" in response.context["form"].errors
        assert settings()["ARCHIVE_STORAGE_REVISION"] == revision
        assert read_config() == (metadata, options)


def test_missing_mount_blocks_native_snapshot_deletion_and_replay(admin_client, snapshot):
    from archivebox.config.constants import CONSTANTS
    from archivebox.core.models import Snapshot
    from archivebox.storage.service import StorageUnavailable, assert_archive_available, mount_path, update_settings

    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.save(update_fields=["config"])
    archive = CONSTANTS.ARCHIVE_DIR
    archive.mkdir(exist_ok=True)
    original = archive.with_name("archive.preserved-test")
    archive.rename(original)
    revision = "0" * 32
    target = mount_path(revision)
    target.mkdir(parents=True)
    archive.symlink_to(target)
    update_settings(
        ARCHIVE_STORAGE_ACTIVE=revision,
        BASE_URL="http://archivebox.localhost:5797",
        SERVER_SECURITY_MODE="safe-subdomains-fullreplay",
    )
    from archivebox.misc.checks import check_data_folder

    check_data_folder()
    assert not (target / "users").exists()
    with pytest.raises(StorageUnavailable):
        assert_archive_available()
    from archivebox.services.runner import run_due_snapshot

    previous_state = (snapshot.status, snapshot.retry_at, snapshot.modified_at)
    with pytest.raises(StorageUnavailable):
        run_due_snapshot(snapshot, lock_seconds=60)
    snapshot.refresh_from_db()
    assert (snapshot.status, snapshot.retry_at, snapshot.modified_at) == previous_state
    snapshot_id = snapshot.pk
    with pytest.raises(StorageUnavailable):
        snapshot.delete()
    assert Snapshot.objects.filter(pk=snapshot_id).exists()
    # The canonical route redirects to replay; use the original-domain route
    # with a public native Snapshot so access has already been authorized.
    from urllib.parse import urlsplit

    response = admin_client.get(urlsplit(snapshot.url).path or "/", HTTP_HOST=f"{snapshot.domain}.archivebox.localhost:5797")
    assert response.status_code == 503
    assert list(target.iterdir()) == []
    assert original.is_dir()


def test_archive_cutover_lock_excludes_real_capture_access(tmp_path):
    from archivebox.storage.service import archive_access, private_dir

    entered = tmp_path / "exclusive-entered"
    attempted = tmp_path / "exclusive-attempted"
    script = "import fcntl,sys; from pathlib import Path; f=open(sys.argv[1],'a+'); Path(sys.argv[3]).write_text('attempting'); fcntl.flock(f,fcntl.LOCK_EX); Path(sys.argv[2]).write_text('acquired')"
    with archive_access():
        process = subprocess.Popen([sys.executable, "-c", script, str(private_dir() / "archive.lock"), str(entered), str(attempted)])
        try:
            deadline = time.monotonic() + 5
            while not attempted.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert attempted.read_text() == "attempting"
            assert process.poll() is None and not entered.exists()
        except BaseException:
            process.kill()
            process.wait()
            raise
    assert process.wait(timeout=5) == 0
    assert entered.read_text() == "acquired"


def test_storage_overview_uses_recorded_capture_totals_and_labels_host_metrics(admin_client, snapshot):
    import gzip
    from pathlib import Path
    from archivebox.core.models import Snapshot
    from archivebox.config.constants import CONSTANTS

    # Reuse real captured HTML; overview totals come from stored metadata and
    # remain available even when the archive filesystem is disconnected.
    body = gzip.decompress((Path(__file__).parent / "fixtures/original-domain-replay/front.html.gz").read_bytes())
    output = snapshot.output_dir / "dom/output.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(body)
    Snapshot.objects.filter(pk=snapshot.pk).update(output_size=len(body), status=Snapshot.StatusChoices.SEALED)
    response = admin_client.get("/admin/storage/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["archive_stats"] == {"total": 1, "sealed": 1, "recorded_bytes": len(body)}
    assert response.context["archive_path"] == str(CONSTANTS.ARCHIVE_DIR)
    assert response.context["storage_type"] == "Local filesystem"
    assert b"Recorded capture bytes" in response.content
    assert b"not remote quota" in response.content
    assert b"All host disks" in response.content
    assert b"Local collection disk free" in response.content
    if not response.context["io_known"]:
        assert b"Unknown" in response.content


def test_storage_diagnostics_reports_actual_database_and_resolves_local_symlinks(admin_client, tmp_path):
    from pathlib import Path
    import os
    import psutil
    from django.db import connection
    from archivebox.config.constants import CONSTANTS
    from archivebox.storage.diagnostics import LOCAL_FILESYSTEMS

    # A real additional SQLite file reached through a symlink must not replace
    # the configured database in diagnostics or invent a network classification.
    import sqlite3

    extra = tmp_path / "additional.sqlite3"
    with sqlite3.connect(extra) as db:
        db.execute("CREATE TABLE review (id INTEGER PRIMARY KEY)")
    conventional = CONSTANTS.DATA_DIR / "index.sqlite3"
    actual = Path(connection.settings_dict["NAME"])
    assert os.path.abspath(actual) != str(conventional)
    assert not conventional.exists()
    conventional.symlink_to(extra)
    response = admin_client.get("/admin/storage/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    diagnostics = response.context["diagnostics"]
    rows = {row["label"]: row for row in diagnostics["rows"]}
    assert rows["Active SQLite database"]["path"] == os.path.abspath(actual)
    assert rows["SQLite WAL"]["path"] == os.path.abspath(str(actual) + "-wal")
    assert rows["SQLite shared memory"]["path"] == os.path.abspath(str(actual) + "-shm")
    extra_row = rows["Additional index.sqlite3 (not active)"]
    native_mount = max(
        (mount for mount in psutil.disk_partitions(all=True) if extra.resolve().is_relative_to(Path(mount.mountpoint))),
        key=lambda mount: len(Path(mount.mountpoint).parts),
    )
    assert extra_row["filesystem"] == native_mount.fstype
    if native_mount.fstype in LOCAL_FILESYSTEMS:
        assert extra_row["resolved"] == str(extra.resolve())
        assert extra_row["locality"] == "Local"
        assert extra_row["free"] > 0
        assert extra_row["permissions"].endswith("RW")
        assert not diagnostics["sqlite_network_paths"]
    for label in (
        "Collection data",
        "Primary archive",
        "Configuration",
        "Browser profiles",
        "Logs",
        "Temporary files",
        "Installed binaries",
        "rclone write cache",
    ):
        assert rows[label]["path"].startswith("/")
    assert b"Filesystem diagnostics" in response.content
    assert b"Server requirements" not in response.content
    assert b"SQLite database on network storage" not in response.content
