"""
Real-file / real-DB tests for the index <-> DB tag merge used by
`archivebox update` / scheduled maintenance (see issue #1626:
"keeps readding a certain tag to items").

The snapshot index on disk (index.json / index.jsonl) and the database are
merged in both directions:

- DB is source of truth for the current tag set (write_index_jsonl).
- The index is trusted for tags the DB row does not have yet
  (_merge_tags_from_index / reconcile_with_index).

If the two sides ever diverge (a tag removed in the DB while the on-disk
index still carries it, e.g. after a migration replay or a legacy index.json
left behind by a 0.7.x/0.8.x install), the merge must still be idempotent:
running it again must not resurrect a tag the user deleted.
"""

import json

import pytest

from archivebox.crawls.models import Crawl
from archivebox.core.models import Snapshot, Tag


def _make_snapshot(tmp_path, tags=("to-be-reviewed",)):
    from archivebox.base_models.models import get_or_create_system_user_pk

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        title="Example Domain",
        status=Snapshot.StatusChoices.SEALED,
    )
    if tags:
        snapshot.save_tags(tags)
    output_dir = snapshot.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.jsonl").unlink(missing_ok=True)  # test manages index contents
    return snapshot, output_dir


def _tag_names(snapshot) -> set[str]:
    snapshot.refresh_from_db()
    return set(snapshot.tags.values_list("name", flat=True))


@pytest.mark.django_db
def test_reconcile_does_not_readd_tag_removed_from_db(tmp_path):
    """User deletes a tag in the DB; a stale index.json still lists it.

    reconcile_with_index (the update / scheduled-update path) must add tags
    missing from the DB, but must not resurrect tags that were already
    present in the index when reconciliation started.
    """
    snapshot, output_dir = _make_snapshot(tmp_path, tags=("to-be-reviewed",))
    (output_dir / "index.json").write_text(
        json.dumps(
            {
                "url": snapshot.url,
                "timestamp": snapshot.timestamp,
                "title": snapshot.title,
                "tags": "to-be-reviewed",
                "archive_results": [],
            },
        ),
    )

    # User removes the tag through the same path the admin UI / API use.
    # This must keep the on-disk index in sync so a later reconcile cannot
    # read the stale index and resurrect the tag.
    snapshot.save_tags([])
    assert _tag_names(snapshot) == set()

    # Nightly scheduled update reconciles DB with the (stale) index.
    snapshot.reconcile_with_index()

    assert _tag_names(snapshot) == set()


@pytest.mark.django_db
def test_convert_index_json_to_jsonl_normalizes_index_tags(tmp_path):
    """Legacy index.json conversion must normalize the index tags the same
    way the DB stores them (sanitize + strip + dedupe).

    This keeps the on-disk index and the DB tag sets textually identical, so
    _merge_tags_from_index stays a true no-op when nothing changed - the
    exact failure mode behind #1626.
    """
    snapshot, output_dir = _make_snapshot(tmp_path, tags=("To-Be-Reviewed", "zeta", "alpha"))
    legacy_tags = " to-be-reviewed , zeta, , alpha "  # messy, un-normalized
    (output_dir / "index.json").write_text(
        json.dumps(
            {
                "url": snapshot.url,
                "timestamp": snapshot.timestamp,
                "title": snapshot.title,
                "tags": legacy_tags,
                "archive_results": [],
            },
        ),
    )

    assert snapshot.convert_index_json_to_jsonl(output_dir=output_dir) is True
    converted = json.loads((output_dir / "index.jsonl").read_text().splitlines()[0])
    assert converted["tags"] == "alpha,to-be-reviewed,zeta"


@pytest.mark.django_db
def test_merge_tags_from_index_is_idempotent_when_in_sync(tmp_path):
    """When DB and index agree, the merge adds nothing and does not
    re-create Tag rows (idempotency of the normal nightly path)."""
    snapshot, output_dir = _make_snapshot(tmp_path, tags=("to-be-reviewed",))
    (output_dir / "index.json").write_text(
        json.dumps(
            {
                "url": snapshot.url,
                "timestamp": snapshot.timestamp,
                "title": snapshot.title,
                "tags": "to-be-reviewed",
                "archive_results": [],
            },
        ),
    )

    before = Tag.objects.count()
    snapshot.reconcile_with_index()
    snapshot.reconcile_with_index()

    assert _tag_names(snapshot) == {"to-be-reviewed"}
    assert Tag.objects.count() == before
