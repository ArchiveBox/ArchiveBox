"""Real folder mutations deliver real script actions using the shared query."""

import json

import pytest

from archivebox.api.models import OutboundWebhook
from archivebox.core.models import ArchiveResult, Folder, Snapshot, Tag
from archivebox.crawls.models import Crawl

pytestmark = pytest.mark.django_db(transaction=True)


def leaf(field, lookup, value, **options):
    return dict(field=field, lookup=lookup, value=value, **options)


def subscribe(folder, admin_user, tmp_path):
    destination = tmp_path / "memberships.jsonl"
    code = f"import sys, pathlib\nwith pathlib.Path({str(destination)!r}).open('a') as out: out.write(sys.stdin.read() + '\\n')"
    for signal in ("FOLDER_ENTERED", "FOLDER_LEFT"):
        OutboundWebhook.objects.create(
            name=f"{folder.name} {signal}",
            ref="archivebox.core.models.Snapshot",
            signal=signal,
            folder=folder,
            created_by=admin_user,
            actions=[dict(type="python", code=code)],
        )
    return destination


def delivered(path):
    if not path.exists():
        return []
    return [(row["event"], row["id"], row["folder_id"]) for row in map(json.loads, path.read_text().splitlines())]


def test_normal_smart_and_nested_membership(admin_user, tmp_path):
    root = Folder.objects.create(name="News")
    middle = Folder.objects.create(name="Sources", parent=root)
    manual = Folder.objects.create(name="FB", parent=middle)
    smart = Folder.objects.create(name="X", parent=middle, rules=leaf("tags__name", "exact", "news"))
    path = subscribe(root, admin_user, tmp_path)
    subscribe(middle, admin_user, tmp_path)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, folder=manual)
    assert set(delivered(path)) == {("FOLDER_ENTERED", str(snapshot.pk), str(folder.pk)) for folder in (root, middle)}
    path.write_text("")
    tag = Tag.objects.create(name="news")
    snapshot.add_tag_ids([tag.pk])
    Folder.move_snapshots(Snapshot.objects.filter(pk=snapshot.pk), None)
    assert delivered(path) == []
    snapshot.remove_tag_ids([tag.pk])
    assert set(delivered(path)) == {("FOLDER_LEFT", str(snapshot.pk), str(folder.pk)) for folder in (root, middle)}
    assert list(Snapshot.objects.in_folder(root.pk)) == []
    assert list(Snapshot.objects.in_folder(smart.pk)) == []


def test_limit_sort_eviction_bulk_updates_and_reverse_tags(admin_user, tmp_path):
    folder = Folder.objects.create(name="Top news", rules=leaf("tags__name", "exact", "news", limit=1, sort="-depth"))
    parent = Folder.objects.create(name="News")
    folder.parent = parent
    folder.save()
    path = subscribe(parent, admin_user, tmp_path)
    subscribe(folder, admin_user, tmp_path)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    first = Snapshot.objects.create(url=crawl.urls, crawl=crawl, depth=1)
    second = Snapshot.objects.create(url="https://news.ycombinator.com/newest", crawl=crawl, depth=2)
    tag = Tag.objects.create(name="news")
    tag.snapshot_set.add(first, second)
    assert set(delivered(path)) == {("FOLDER_ENTERED", str(second.pk), str(f.pk)) for f in (folder, parent)}
    path.write_text("")
    Snapshot.objects.filter(pk=first.pk).update(depth=3)
    assert set(delivered(path)) == {
        (signal, str(snapshot.pk), str(f.pk))
        for signal, snapshot in (("FOLDER_LEFT", second), ("FOLDER_ENTERED", first))
        for f in (folder, parent)
    }
    assert list(Snapshot.objects.in_folder(folder.pk)) == [first]
    assert list(Snapshot.objects.in_folder(parent.pk)) == [first]
    path.write_text("")
    tag.snapshot_set.remove(first)
    assert set(delivered(path)) == {
        (signal, str(snapshot.pk), str(f.pk))
        for signal, snapshot in (("FOLDER_LEFT", first), ("FOLDER_ENTERED", second))
        for f in (folder, parent)
    }


def test_folder_rule_edits_reparent_and_related_outputs(admin_user, tmp_path):
    root = Folder.objects.create(name="News")
    child = Folder.objects.create(name="Large", parent=root, rules=leaf("archiveresult__output_size", "gt", 100))
    path = subscribe(root, admin_user, tmp_path)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="wget", output_size=10)
    assert delivered(path) == []
    ArchiveResult.objects.filter(pk=result.pk).update(output_size=200)
    assert delivered(path) == [("FOLDER_ENTERED", str(snapshot.pk), str(root.pk))]
    child.rules = leaf("archiveresult__output_size", "gt", 300)
    child.save()
    assert delivered(path)[-1] == ("FOLDER_LEFT", str(snapshot.pk), str(root.pk))
    child.rules = leaf("archiveresult__output_size", "gt", 100)
    child.save()
    assert delivered(path)[-1] == ("FOLDER_ENTERED", str(snapshot.pk), str(root.pk))
    child.parent = None
    child.save()
    assert delivered(path)[-1] == ("FOLDER_LEFT", str(snapshot.pk), str(root.pk))


def test_bulk_insert_limited_parent_and_rollback(admin_user, tmp_path):
    from django.db import transaction

    root = Folder.objects.create(name="Latest", rules=leaf("url", "icontains", "ycombinator", sort="-created_at", limit=1))
    path = subscribe(root, admin_user, tmp_path)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    first = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    path.write_text("")
    second = Snapshot(url="https://news.ycombinator.com/newest", timestamp="1700000001", crawl=crawl)
    Snapshot.objects.bulk_create([second])
    assert delivered(path) == [
        ("FOLDER_LEFT", str(first.pk), str(root.pk)),
        ("FOLDER_ENTERED", str(second.pk), str(root.pk)),
    ]
    path.write_text("")
    with pytest.raises(RuntimeError, match="rollback"):
        with transaction.atomic():
            Snapshot.objects.filter(pk=second.pk).update(url="https://example.org/")
            raise RuntimeError("rollback")
    assert delivered(path) == []
    assert list(Snapshot.objects.in_folder(root.pk)) == [second]


def test_direct_tag_clear_and_delete_deliver_once(admin_user, tmp_path):
    folder = Folder.objects.create(name="Tagged", rules=leaf("tags__name", "exact", "news"))
    path = subscribe(folder, admin_user, tmp_path)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    tag = Tag.objects.create(name="news")
    snapshot.tags.add(tag)
    assert delivered(path) == [("FOLDER_ENTERED", str(snapshot.pk), str(folder.pk))]
    path.write_text("")
    snapshot.tags.clear()
    assert delivered(path) == [("FOLDER_LEFT", str(snapshot.pk), str(folder.pk))]
    snapshot.tags.add(tag)
    path.write_text("")
    tag.delete()
    assert delivered(path) == [("FOLDER_LEFT", str(snapshot.pk), str(folder.pk))]


def test_crawl_and_tag_queryset_changes(admin_user, tmp_path):
    folder = Folder.objects.create(name="Completed", rules=leaf("crawl__status", "exact", "sealed"))
    path = subscribe(folder, admin_user, tmp_path)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    Crawl.objects.filter(pk=crawl.pk).update(status="sealed")
    assert delivered(path) == [("FOLDER_ENTERED", str(snapshot.pk), str(folder.pk))]
    tagged = Folder.objects.create(name="Renamed tag", rules=leaf("tags__name", "exact", "news"))
    subscribe(tagged, admin_user, tmp_path)
    tag = Tag.objects.create(name="old")
    snapshot.tags.add(tag)
    path.write_text("")
    Tag.objects.filter(pk=tag.pk).update(name="news")
    assert delivered(path) == [("FOLDER_ENTERED", str(snapshot.pk), str(tagged.pk))]


def test_large_limited_folder_eviction_uses_frozen_query(admin_user, tmp_path):
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    rows = [
        Snapshot(url=f"https://news.ycombinator.com/item?id={i}", timestamp=str(1700000000 + i), crawl=crawl, output_size=i)
        for i in range(1003)
    ]
    Snapshot.objects.bulk_create(rows)
    root = Folder.objects.create(name="Large latest")
    folder = Folder.objects.create(
        name="Large window",
        parent=root,
        rules=leaf("domain", "exact", "news.ycombinator.com", limit=1001, sort="-output_size"),
    )
    path = subscribe(root, admin_user, tmp_path)
    Snapshot.objects.filter(pk=rows[0].pk).update(output_size=2000)
    assert set(delivered(path)) == {
        ("FOLDER_LEFT", str(rows[2].pk), str(root.pk)),
        ("FOLDER_ENTERED", str(rows[0].pk), str(root.pk)),
    }
    assert Snapshot.objects.in_folder(folder.pk).count() == 1001
    assert Snapshot.objects.in_folder(folder.pk).first() == rows[0]
    assert not Snapshot.objects.in_folder(folder.pk).filter(pk=rows[2].pk).exists()


def test_parent_normalization_does_not_emit_transient_membership(admin_user, tmp_path):
    from django.db import transaction

    parent = Folder.objects.create(name="News")
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, folder=parent)
    path = subscribe(parent, admin_user, tmp_path)
    with transaction.atomic():
        Folder.objects.create(name="Sources", parent=parent)
    assert list(Snapshot.objects.in_folder(parent.pk)) == [snapshot]
    assert delivered(path) == []


def test_crawl_queryset_lifecycle_fires_once_on_real_transitions(admin_user, tmp_path):
    from asgiref.sync import async_to_sync

    destination = tmp_path / "crawl-events.jsonl"
    code = f"import sys, pathlib\nwith pathlib.Path({str(destination)!r}).open('a') as out: out.write(sys.stdin.read() + '\\n')"
    for signal in ("STARTED", "COMPLETED"):
        OutboundWebhook.objects.create(
            name=f"Crawl {signal}",
            ref="archivebox.crawls.models.Crawl",
            signal=signal,
            created_by=admin_user,
            actions=[dict(type="python", code=code)],
        )
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    queryset = Crawl.objects.filter(pk=crawl.pk)
    async_to_sync(queryset.aupdate)(status="started")
    queryset.update(status="started")
    async_to_sync(queryset.aupdate)(status="sealed")
    queryset.update(status="sealed")
    rows = [json.loads(line) for line in destination.read_text().splitlines()]
    assert [(row["event"], row["id"], row["status"]) for row in rows] == [
        ("STARTED", str(crawl.pk), "started"),
        ("COMPLETED", str(crawl.pk), "sealed"),
    ]


def test_native_tag_helpers_emit_existing_m2m_hooks_once(admin_user, tmp_path):
    destination = tmp_path / "tag-events.jsonl"
    code = f"import sys, pathlib\nwith pathlib.Path({str(destination)!r}).open('a') as out: out.write(sys.stdin.read() + '\\n')"
    for signal in ("M2M_ADD", "M2M_REMOVE"):
        OutboundWebhook.objects.create(
            name=f"Snapshot {signal}",
            ref="archivebox.core.models.Snapshot",
            signal=signal,
            created_by=admin_user,
            actions=[dict(type="python", code=code)],
        )
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    tag = Tag.objects.create(name="news")
    snapshot.add_tag_ids([tag.pk])
    snapshot.add_tag_ids([tag.pk])
    assert list(snapshot.tags.values_list("name", flat=True)) == ["news"]
    assert snapshot.remove_tag_ids([tag.pk]) == 1
    assert snapshot.remove_tag_ids([tag.pk]) == 0
    rows = [json.loads(line) for line in destination.read_text().splitlines()]
    assert [(row["event"], row["id"]) for row in rows] == [
        ("M2M_ADD", str(snapshot.pk)),
        ("M2M_REMOVE", str(snapshot.pk)),
    ]


def test_creation_action_tags_survive_crawl_defaults_and_enter_folder(admin_user, tmp_path):
    folder = Folder.objects.create(name="Tagged by webhook", rules=leaf("tags__name", "exact", "news"))
    path = subscribe(folder, admin_user, tmp_path)
    OutboundWebhook.objects.create(
        name="Tag new snapshot",
        ref="archivebox.core.models.Snapshot",
        signal="CREATE",
        created_by=admin_user,
        actions=[dict(type="add_tags", add_tags="news")],
    )
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user, tags_str="initial")
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    assert set(snapshot.tags.values_list("name", flat=True)) == {"initial", "news"}
    assert delivered(path) == [("FOLDER_ENTERED", str(snapshot.pk), str(folder.pk))]
