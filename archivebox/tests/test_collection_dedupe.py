import asyncio
import hashlib
import os
import sqlite3
from contextlib import closing
from urllib.parse import urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from archivebox.config.constants import CONSTANTS
from archivebox.core.models import Snapshot
from archivebox.core.routes_util import build_snapshot_url
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.workers.runner import CrawlRunner


@pytest.mark.django_db(transaction=True)
def test_capture_dedup_scope_and_verified_backfill(admin_user, client):
    other = get_user_model().objects.create(username="another")
    persona = Persona.objects.create(created_by=admin_user, name="dedup")

    def capture(owner, profile=None, visibility="public", enabled=True):
        url = "https://example.org/archive"
        crawl = Crawl.objects.create(
            created_by=owner,
            persona=profile,
            urls=url,
            config={"PLUGINS": "hashes", "HASHES_COLLECTION_DEDUP": enabled, "PERMISSIONS": visibility},
        )
        snap = Snapshot.objects.create(crawl=crawl, url=url, config={"PERMISSIONS": visibility})
        dest = snap.output_dir / "download" / "content.txt"
        dest.parent.mkdir(parents=True)
        dest.write_bytes(b"content")
        dest.with_name("other.bin").write_bytes(b"different")
        asyncio.run(CrawlRunner(crawl).run())
        snap.refresh_from_db()
        assert snap.status == "sealed"
        assert snap.archiveresult_set.filter(plugin="hashes", status="succeeded").exists()
        return dest

    first = capture(admin_user)
    disabled = capture(admin_user, enabled=False)
    assert not disabled.samefile(first)
    linked = capture(admin_user)
    assert linked.samefile(first)
    foreign = [capture(other), capture(admin_user, persona), capture(admin_user, visibility="private")]
    assert all(not path.samefile(first) for path in foreign)
    disabled.write_bytes(b"changed")  # Historical manifest has same length and obsolete digest.
    call_command("dedupe_files")
    assert disabled.read_bytes() == b"changed" and not disabled.samefile(first)
    url = urlsplit(build_snapshot_url(disabled.parents[1].name, "download/content.txt"))

    def read(target):
        disabled.unlink(missing_ok=True)
        disabled.symlink_to(os.path.relpath(target, disabled.parent))
        response = client.get(url.path, {"raw": "1"}, HTTP_HOST=url.netloc, HTTP_RANGE="bytes=1-3")
        try:
            return response.status_code, b"".join(response.streaming_content) if response.streaming else b""
        finally:
            response.close()

    assert read(first) == (206, b"ont")
    assert read(linked) == (206, b"ont")
    assert read(first.with_name("other.bin")) == (206, b"iff")
    unarchived = first.with_name("unarchived")
    unarchived.write_bytes(b"unarchived")
    for denied in (*foreign, unarchived):
        assert read(denied)[0] == 404
    source_snapshot = Snapshot.objects.get(pk=first.parents[1].name)
    source_snapshot.crawl.persona = persona
    source_snapshot.crawl.save(update_fields=["persona"])
    assert read(first)[0] == 404
    first.unlink()
    assert linked.read_bytes() == b"content"
    elected = capture(admin_user)
    assert os.path.isfile(elected)
    assert capture(admin_user).samefile(elected)
    # The index is a lookup hint. Even identical bytes at an unarchived
    # source path must never become the backing file for a captured output.
    private = elected.with_name("unarchived")
    private.write_bytes(elected.read_bytes())
    with closing(sqlite3.connect(CONSTANTS.DATA_DIR / "hashes.sqlite3")) as db, db:
        changed = db.execute(
            "UPDATE files SET path=? WHERE snapshot=? AND hash=?",
            ("download/unarchived", Snapshot.objects.get(pk=elected.parents[1].name).pk.bytes, hashlib.sha256(b"content").digest()),
        )
        assert changed.rowcount == 1
    assert not capture(admin_user).samefile(private)


@pytest.mark.django_db(transaction=True)
def test_dedup_keeps_surviving_file_when_storage_cannot_share(admin_user, client):
    from archivebox.core.collection_dedupe import replace

    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.org/retained")
    first = Snapshot.objects.create(crawl=crawl, url="https://example.org/first", status="sealed")
    second = Snapshot.objects.create(crawl=crawl, url="https://example.org/second", status="sealed")
    source = first.output_dir / "download" / "content.txt"
    retained = second.output_dir / "download" / "content.txt"
    for path in (source, retained):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"retained capture")
    # Exercise the real replacement path after the runner has learned that
    # this device pair does not support either safe sharing method.
    pair = (source.stat().st_dev, retained.stat().st_dev)
    outcome = replace(source, retained, {(*pair, "hardlink"), (*pair, "clone")})
    first_id = first.pk
    first.delete()
    assert not source.exists() and not Snapshot.objects.filter(pk=first_id).exists()
    assert Snapshot.objects.filter(pk=second.pk).exists()
    assert retained.read_bytes() == b"retained capture"
    assert outcome == "kept" and not retained.is_symlink()

    url = urlsplit(build_snapshot_url(str(second.pk), "download/content.txt"))
    response = client.get(url.path, {"raw": "1"}, HTTP_HOST=url.netloc, HTTP_RANGE="bytes=0-7")
    try:
        assert response.status_code == 206
        assert b"".join(response.streaming_content) == b"retained"
    finally:
        response.close()
