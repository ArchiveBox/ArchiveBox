"""Explicit maintenance must count retained bytes without inventing capture results."""

import hashlib
import json
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("filtered", [True, False])
def test_rescan_counts_resultless_payload_without_recapture(initialized_archive, filtered):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(
            urls="https://archivebox.io/tests/preserved-payload",
            created_by_id=get_or_create_system_user_pk(),
            status="sealed",
        )
        selected = Snapshot.objects.create(
            url=crawl.urls,
            crawl=crawl,
            status="sealed",
            retry_at=None,
            fs_version=Snapshot._fs_current_version(),
        )
        other = Snapshot.objects.create(
            url="https://archivebox.io/tests/unselected-payload",
            crawl=crawl,
            status="sealed",
            retry_at=None,
            fs_version=Snapshot._fs_current_version(),
        )
        for snapshot in (selected, other):
            snapshot.output_dir.mkdir(parents=True, exist_ok=True)
            snapshot.write_index_jsonl()
        selected_id, other_id = selected.pk, other.pk
        selected_dir, other_dir = selected.output_dir, other.output_dir
        timestamp = selected.timestamp
        other_modified = other.modified_at

    payload = (Path(__file__).parent / "fixtures/bablosoft-lazy-image/work-1.png").read_bytes()
    (selected_dir / "screenshot.png").write_bytes(payload)
    article = b"<html><title>Preserved capture</title><body>Existing archived content.</body></html>"
    (selected_dir / "output.html").write_bytes(article)
    (selected_dir / "index.html").write_text("<html>Generated archive navigation, not captured output.</html>")
    (selected_dir / ".DS_Store").write_bytes(b"not captured output")
    (other_dir / "untouched.txt").write_bytes(b"other snapshot")
    (selected_dir / "outside-link").symlink_to(other_dir / "untouched.txt")
    expected_size = len(payload) + len(article)
    before_hash = hashlib.sha256(payload).hexdigest()
    args = ["update", "--rescan", "--migrate-only"]
    if filtered:
        args.extend(["--filter-type", "timestamp", timestamp])
    prior_modified = None

    for _ in range(2):
        result = run_archivebox_cmd(args, cwd=initialized_archive, env=cli_env(disable_extractors=True), timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        with use_archivebox_db(initialized_archive):
            refreshed = Snapshot.objects.get(pk=selected_id)
            assert refreshed.output_size == expected_size
            assert refreshed.status == "sealed"
            assert refreshed.retry_at is None
            assert refreshed.downloaded_at is None
            assert not ArchiveResult.objects.filter(snapshot_id=selected_id).exists()
            if prior_modified is not None:
                assert refreshed.modified_at == prior_modified
            prior_modified = refreshed.modified_at
            untouched = Snapshot.objects.get(pk=other_id)
            assert untouched.status == "sealed" and untouched.retry_at is None
            assert not ArchiveResult.objects.filter(snapshot_id=other_id).exists()
            if filtered:
                assert untouched.output_size == 0
                assert untouched.modified_at == other_modified
            else:
                assert untouched.output_size == len(b"other snapshot")
        assert hashlib.sha256((selected_dir / "screenshot.png").read_bytes()).hexdigest() == before_hash
        assert (selected_dir / "output.html").read_bytes() == article
        assert (other_dir / "untouched.txt").read_bytes() == b"other snapshot"
        records = [json.loads(line) for line in (selected_dir / "index.jsonl").read_text().splitlines()]
        assert next(record for record in records if record["type"] == "Snapshot")["output_size"] == expected_size
        assert not any(record["type"] == "ArchiveResult" for record in records)
