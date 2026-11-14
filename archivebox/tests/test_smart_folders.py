import pytest
from django.core.exceptions import ValidationError
from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.core.smart_folders import RuleQuery
from archivebox.crawls.models import Crawl

pytestmark = pytest.mark.django_db


def leaf(field, lookup, value):
    return {"field": field, "lookup": lookup, "value": value}


def group(op, *rules):
    return {"op": op, "rules": list(rules)}


def test_rules_use_models_and_boolean_set_semantics(admin_user):
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    first = Snapshot.objects.create(url="https://www.youtube.com/watch?v=first", title="Video", crawl=crawl)
    second = Snapshot.objects.create(url="https://example.org/", title="Other", crawl=crawl)
    first.tags.add(Tag.objects.create(name="video"), Tag.objects.create(name="saved"))
    query = RuleQuery()
    rule = group(
        "AND",
        leaf("tags__name", "exact", "video"),
        leaf("tags__name", "exact", "saved"),
        group("NOT", leaf("title", "icontains", "Other")),
    )
    assert list(Snapshot.objects.filter(query.compile(rule))) == [first]
    assert list(Snapshot.objects.filter(query.compile(group("NOT", leaf("tags__name", "exact", "video"))))) == [second]
    assert list(Snapshot.objects.filter(query.compile(leaf("domain", "iendswith", "youtube.com")))) == [first]
    schema = {field["name"]: field for field in query.schema()}
    assert "archiveresult__output_size" in schema
    assert schema["archiveresult__output_size"]["type"] == "number"
    assert "crawl__created_by__password" not in schema


def test_parent_union_and_live_changes(admin_user):
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    parent = Folder.objects.create(name="Reading")
    manual = Folder.objects.create(name="Saved", parent=parent)
    smart = Folder.objects.create(name="Videos", parent=parent, rules=leaf("url", "icontains", "youtube.com"))
    first = Snapshot.objects.create(url="https://youtube.com/one", crawl=crawl, folder=manual)
    second = Snapshot.objects.create(url="https://youtube.com/two", crawl=crawl)
    other = Snapshot.objects.create(url="https://example.org/", crawl=crawl)
    assert set(Folder.select_snapshots(Snapshot.objects.all(), parent.pk).values_list("pk", flat=True)) == {first.pk, second.pk}
    assert Folder.select_snapshots(Snapshot.objects.all(), parent.pk).count() == 2
    Snapshot.objects.filter(pk=other.pk).update(url="https://youtube.com/three")
    assert Folder.select_snapshots(Snapshot.objects.all(), smart.pk).count() == 3
    smart.rules = leaf("folder", "in_folder", str(parent.pk))
    with pytest.raises(ValidationError, match="cycle"):
        smart.save()


def test_invalid_rules_rejected():
    for rule in [
        group("AND"),
        leaf("title__regex", "exact", "x"),
        leaf("crawl__created_by__password", "exact", "x"),
        leaf("depth", "gt", "bad"),
        group("NOT", leaf("title", "exact", "x"), leaf("title", "exact", "y")),
    ]:
        with pytest.raises(ValidationError):
            RuleQuery().compile(rule)


def test_youtube_size_and_related_negation(admin_user):
    from archivebox.core.models import ArchiveResult

    crawl = Crawl.objects.create(urls="https://youtube.com/", created_by=admin_user)
    large = Snapshot.objects.create(url="https://www.youtube.com/watch?v=large", crawl=crawl)
    small = Snapshot.objects.create(url="https://www.youtube.com/watch?v=small", crawl=crawl)
    unrelated = Snapshot.objects.create(url="https://example.org/watch", crawl=crawl)
    ArchiveResult.objects.bulk_create(
        [
            ArchiveResult(snapshot=large, plugin="ytdlp", output_size=1_250_000_000, status="succeeded"),
            ArchiveResult(snapshot=large, plugin="title", output_size=42, status="succeeded"),
            ArchiveResult(snapshot=small, plugin="ytdlp", output_size=500_000, status="succeeded"),
            ArchiveResult(snapshot=unrelated, plugin="ytdlp", output_size=2_000_000_000, status="succeeded"),
        ],
    )
    size = leaf("archiveresult__output_size", "gt", {"amount": "1", "unit": "GB"})
    folder = Folder.objects.create(name="YouTube (>1gb)", rules=group("AND", leaf("domain", "iendswith", "youtube.com"), size))
    assert list(Folder.select_snapshots(Snapshot.objects.all(), folder.pk)) == [large]
    assert set(Snapshot.objects.filter(RuleQuery().compile(group("NOT", size)))) == {small}
    assert set(Snapshot.objects.filter(RuleQuery().compile(leaf("tags", "isnull", None)))) == {large, small, unrelated}


@pytest.mark.django_db(transaction=True)
def test_parent_converts_to_child_union_and_moves_in_small_commits(admin_user):
    from django.db import connection
    from archivebox.core.smart_folders import CHILDREN_RULES

    parent = Folder.objects.create(name="Saved")
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user, folder=parent)
    Snapshot.objects.bulk_create(
        [
            Snapshot(url=f"https://news.ycombinator.com/item?id={index}", timestamp=str(1700000000 + index), crawl=crawl, folder=parent)
            for index in range(1201)
        ],
        batch_size=100,
    )
    write_sizes = []

    def observe(execute, sql, params, many, context):
        if sql.startswith('UPDATE "core_snapshot"'):
            write_sizes.append(len(params))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(observe):
        Folder.objects.create(name="Recent", parent=parent)
    parent.refresh_from_db()
    items = parent.children.get(name="Items")
    assert parent.rules == CHILDREN_RULES
    assert not parent.snapshots.exists()
    assert items.snapshots.count() == 1201
    assert len(write_sizes) == 3 and max(write_sizes) < 510
    assert Folder.select_snapshots(Snapshot.objects.all(), parent.pk).count() == 1201
    crawl.refresh_from_db()
    assert crawl.folder_id == items.pk
    new = Snapshot.objects.create(url="https://news.ycombinator.com/newest", crawl=crawl, folder=parent)
    assert new.folder_id == items.pk
    assert Folder.move_snapshots(Snapshot.objects.filter(folder=items), None) == 1202
    assert Snapshot.objects.filter(folder__isnull=True).count() == 1202


@pytest.mark.django_db(transaction=True)
def test_smart_parent_preserves_original_rule_in_items(admin_user):
    rules = leaf("title", "icontains", "news")
    parent = Folder.objects.create(name="News", rules=rules)
    child = Folder.objects.create(name="Saved", parent=parent)
    parent.refresh_from_db()
    assert parent.is_container
    items = parent.children.get(name="Items")
    assert items.rules == rules
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    one = Snapshot.objects.create(url=crawl.urls, title="Hacker News", crawl=crawl)
    two = Snapshot.objects.create(url="https://example.org/", crawl=crawl, folder=child)
    assert set(Folder.select_snapshots(Snapshot.objects.all(), parent.pk)) == {one, two}
    assigned = Snapshot.objects.create(url="https://example.org/new", crawl=crawl, folder=parent)
    assert assigned.folder.name == "Items (2)" and not assigned.folder.is_smart


def test_new_child_cannot_make_circular_union():
    parent = Folder.objects.create(name="Parent")
    with pytest.raises(ValidationError, match="cycle"):
        Folder.objects.create(name="Circular child", parent=parent, rules=leaf("folder", "in_folder", str(parent.pk)))
    assert not parent.children.exists()


def test_rule_form_validation_and_ownership(admin_client, admin_user):
    import json
    from archivebox.tests.conftest import ADMIN_TEST_HOST

    host = {"HTTP_HOST": ADMIN_TEST_HOST}
    url = "/admin/core/folder/save/"
    response = admin_client.post(url, {"name": "Videos", "rules": json.dumps(leaf("domain", "iendswith", "youtube.com"))}, **host)
    assert response.status_code == 200, response.content
    folder = Folder.objects.get(pk=response.json()["id"])
    assert folder.is_smart and folder.created_by == admin_user
    response = admin_client.get("/admin/core/folder/rules/", {"folder_id": str(folder.pk)}, **host)
    assert response.status_code == 200
    assert response.json()["rules"] == folder.rules
    assert "archiveresult__output_size" in {field["name"] for field in response.json()["fields"]}
    response = admin_client.post(url, {"name": "Broken", "rules": json.dumps(leaf("title__regex", "exact", ".*"))}, **host)
    assert response.status_code == 400, response.content
    assert not Folder.objects.filter(name="Broken").exists()


def test_both_tags_without_excluded_tag(admin_user):
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    tags = {name: Tag.objects.create(name=name) for name in ("A", "B", "C")}
    examples = {}
    for index, names in enumerate([("A", "B"), ("A", "B", "C"), ("A",), ("B",), ()]):
        snapshot = Snapshot.objects.create(url=f"https://news.ycombinator.com/item?id={index}", crawl=crawl)
        snapshot.tags.add(*(tags[name] for name in names))
        examples[names] = snapshot
    rules = group("AND", leaf("tags__name", "exact", "A"), leaf("tags__name", "exact", "B"), leaf("tags__name", "not_exact", "C"))
    assert list(Snapshot.objects.filter(RuleQuery().compile(rules))) == [examples[("A", "B")]]


def test_folder_type_is_immutable_and_delete_preserves_snapshots(admin_client, admin_user):
    from archivebox.tests.conftest import ADMIN_TEST_HOST

    host = {"HTTP_HOST": ADMIN_TEST_HOST}
    manual = Folder.objects.create(name="Manual")
    manual.rules = leaf("title", "icontains", "news")
    with pytest.raises(ValidationError, match="type cannot be changed"):
        manual.save()
    smart = Folder.objects.create(name="Smart", rules=leaf("title", "icontains", "news"))
    smart.rules = None
    with pytest.raises(ValidationError, match="type cannot be changed"):
        smart.save()
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, folder_id=manual.pk)
    response = admin_client.post("/admin/core/folder/remove/", {"folder_id": str(manual.pk)}, **host)
    assert response.status_code == 200, response.content
    snapshot.refresh_from_db()
    assert snapshot.folder_id is None
    assert not Folder.objects.filter(pk=manual.pk).exists()


def test_django_select_across_moves_all_matches_and_preserves_exclusions(admin_client, admin_user):
    from archivebox.tests.conftest import ADMIN_TEST_HOST

    source = Folder.objects.create(name="Source")
    target = Folder.objects.create(name="Destination")
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://news.ycombinator.com/item?id={index}",
                timestamp=str(1800000000 + index),
                crawl=crawl,
                folder=source,
                title="selected" if index < 105 else "excluded",
            )
            for index in range(110)
        ],
        batch_size=100,
    )
    response = admin_client.post(
        f"/admin/core/snapshot/?folder={source.pk}&title__exact=selected",
        {
            "action": "move_to_folder",
            "folder_destination": str(target.pk),
            "_selected_action": [str(snapshot.pk) for snapshot in snapshots[:50]],
            "select_across": "1",
            "index": "0",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302, response.content
    assert Snapshot.objects.filter(folder=target, title="selected").count() == 105
    assert Snapshot.objects.filter(folder=source, title="excluded").count() == 5
