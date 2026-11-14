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
        group("AND", leaf("tags__name", "exact", "video"), leaf("tags__name", "exact", "saved")),
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
    rules = group(
        "AND",
        group("AND", leaf("tags__name", "exact", "A"), leaf("tags__name", "exact", "B")),
        leaf("tags__name", "not_exact", "C"),
    )
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


@pytest.mark.parametrize("clear_assignment", [False, True])
def test_django_select_across_moves_all_matches_and_preserves_exclusions(admin_client, admin_user, clear_assignment):
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
            "folder_destination": "" if clear_assignment else str(target.pk),
            "_selected_action": [str(snapshot.pk) for snapshot in snapshots[:50]],
            "select_across": "1",
            "index": "0",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302, response.content
    assert Snapshot.objects.filter(folder=None if clear_assignment else target, title="selected").count() == 105
    assert Snapshot.objects.filter(folder=source, title="excluded").count() == 5


def test_seeded_smart_folder_uses_normal_rules_ordering_and_destinations(admin_user):
    folder = Folder.objects.get(name="📥 Inbox")
    folder.name = "Unassigned"
    folder.position = 10
    folder.save()
    regular = Folder.objects.create(name="Saved", position=1)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, folder=regular)
    assert list(Folder.select_snapshots(Snapshot.objects.all(), folder.pk)) == []
    with pytest.raises(ValidationError, match="Choose a regular folder"):
        Folder.destination(folder.pk)
    assert Folder.move_snapshots(Snapshot.objects.filter(pk=snapshot.pk), None) == 1
    assert list(Folder.select_snapshots(Snapshot.objects.all(), folder.pk)) == [snapshot]
    assert [item.pk for item in Folder.tree()] == [regular.pk, folder.pk]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("field,lookup,value", [("folder", "in_folder", "*"), ("title", "icontains", "news")])
def test_browser_rename_preserves_negated_smart_folder_rules(live_server, admin_user, browser_runtime, field, lookup, value):
    from playwright.sync_api import sync_playwright, expect
    from urllib.parse import urlsplit
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    rules = group("NOT", leaf(field, lookup, value))
    folder = Folder.objects.create(name="Unread", rules=rules)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        row = page.locator(f'.folder-row[data-folder-id="{folder.pk}"]')
        row.hover()
        row.get_by_role("button", name="Actions for Unread", exact=True).click()
        row.get_by_role("menuitem", name="Rename", exact=True).click()
        expect(page.locator(".folder-save")).to_be_enabled()
        page.locator("#folder-name").fill("📥 Reading")
        page.locator(".folder-save").click()
        expect(row).to_have_attribute("data-folder-name", "📥 Reading")
        expect(row.locator(".folder-title-emoji")).to_have_text("📥")
        browser.close()
    folder.refresh_from_db()
    assert folder.name == "📥 Reading"
    assert folder.rules == rules


@pytest.mark.parametrize("op", ["AND", "OR"])
def test_groups_reject_more_than_two_members(op):
    with pytest.raises(ValidationError, match="two"):
        RuleQuery().compile(group(op, leaf("title", "exact", "A"), leaf("title", "exact", "B"), leaf("title", "exact", "C")))


def test_nested_binary_domain_and_status_rules(admin_user):
    crawl = Crawl.objects.create(urls="https://youtube.com/", created_by=admin_user)
    included = [
        Snapshot.objects.create(url=f"https://{domain}/saved", crawl=crawl, status="sealed") for domain in ["youtube.com", "tiktok.com"]
    ]
    Snapshot.objects.create(url="https://youtube.com/failed", crawl=crawl, status="paused")
    Snapshot.objects.create(url="https://tiktok.com/failed", crawl=crawl, status="paused")
    Snapshot.objects.create(url="https://example.org/saved", crawl=crawl, status="sealed")
    rule = group(
        "OR",
        *[
            group("AND", leaf("domain", "iendswith", domain), group("NOT", leaf("status", "exact", "paused")))
            for domain in ["youtube.com", "tiktok.com"]
        ],
    )
    assert set(Snapshot.objects.filter(RuleQuery().compile(rule))) == set(included)
    status = next(field for field in RuleQuery.schema() if field["name"] == "status")
    assert dict(status["choices"]) == dict(Snapshot._meta.get_field("status").flatchoices)


@pytest.mark.parametrize("sort", ["-created_at", "title", "-title", "?"])
@pytest.mark.parametrize("limit", [601, 1101])
def test_sort_limit_apply_to_parent_exports_and_bulk_selection(admin_client, admin_user, sort, limit):
    import json
    from archivebox.tests.conftest import ADMIN_TEST_HOST
    from archivebox.core.exports import get_export_queryset

    source = Folder.objects.create(name="Option source")
    parent = Folder.objects.create(name="Option parent")
    target = Folder.objects.create(name="Option destination")
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://news.ycombinator.com/item?id={index}",
                timestamp=str(1800000000 + index),
                title=f"{1200 - index:04d}" if index % 3 else None,
                crawl=crawl,
                folder=source,
            )
            for index in range(1200)
        ],
    )
    response = admin_client.post(
        "/admin/core/folder/save/",
        {
            "name": "Limited",
            "parent": str(parent.pk),
            "rules": json.dumps({**leaf("folder", "in_folder", str(source.pk)), "sort": sort, "limit": limit}),
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200, response.content
    folder = Folder.objects.get(pk=response.json()["id"])
    expected = list(Snapshot.objects.filter(folder=source).order_by(*RuleQuery.ordering(folder)).values_list("pk", flat=True)[:limit])
    actual = Folder.select_snapshots(Snapshot.objects.all(), folder.pk)
    assert list(actual.values_list("pk", flat=True)) == expected
    assert set(Folder.select_snapshots(Snapshot.objects.all(), parent.pk).values_list("pk", flat=True)) == set(expected)
    assert (
        list(get_export_queryset({"folder": str(folder.pk)}, user=admin_user, public_only=False).values_list("pk", flat=True)) == expected
    )
    if sort == "?":
        assert expected != [snapshot.pk for snapshot in snapshots[:limit]]
        assert list(Folder.select_snapshots(Snapshot.objects.all(), folder.pk).values_list("pk", flat=True)) == expected
    page = admin_client.get(f"/admin/core/snapshot/?folder={folder.pk}", HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200, page.content
    assert [row.pk for row in page.context["cl"].result_list] == expected[: page.context["cl"].list_per_page]
    response = admin_client.post(
        f"/admin/core/snapshot/?folder={parent.pk}",
        {
            "action": "move_to_folder",
            "folder_destination": str(target.pk),
            "_selected_action": [str(expected[0])],
            "select_across": "1",
            "index": "0",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302, response.content
    assert set(Snapshot.objects.filter(folder=target).values_list("pk", flat=True)) == set(expected)
    assert Snapshot.objects.filter(folder=source).count() == 1200 - limit


def test_optional_sort_limit_defaults_validation_and_container_options(admin_user):
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshots = [Snapshot.objects.create(url=f"https://news.ycombinator.com/{index}", crawl=crawl) for index in range(3)]
    folder = Folder.objects.create(name="Unlimited", rules=leaf("url", "icontains", "news.ycombinator.com"))
    assert list(Folder.select_snapshots(Snapshot.objects.all(), folder.pk)) == snapshots[::-1]
    for options in ({"limit": 0}, {"limit": -1}, {"limit": True}, {"limit": 1.5}, {"sort": "tags__name"}, {"sort": "nope"}):
        folder.rules = {**leaf("url", "icontains", "news.ycombinator.com"), **options}
        with pytest.raises(ValidationError):
            folder.full_clean()
    parent = Folder.objects.create(name="Limited container")
    Folder.objects.create(name="First", parent=parent)
    parent.refresh_from_db()
    parent.rules = {**parent.rules, "limit": 1, "sort": "title"}
    parent.save()
    Folder.objects.create(name="Second", parent=parent)
    parent.refresh_from_db()
    assert parent.is_container and parent.rules["limit"] == 1 and parent.rules["sort"] == "title"


def test_public_smart_folder_preserves_limit_order_and_visibility(client, admin_user):
    from django.test import override_settings
    from archivebox.tests.conftest import WEB_TEST_HOST

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshots = [
        Snapshot.objects.create(url=f"https://news.ycombinator.com/{i}", title=str(i), crawl=crawl, config={"PERMISSIONS": "public"})
        for i in range(4)
    ]
    folder = Folder.objects.create(
        name="First three",
        rules={**leaf("url", "icontains", "news.ycombinator.com"), "sort": "title", "limit": 3},
    )
    with override_settings(PUBLIC_INDEX=True):
        response = client.get("/public/", {"folder": str(folder.pk)}, HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    assert list(response.context["object_list"]) == snapshots[:3]
    snapshots[1].config = {"PERMISSIONS": "private"}
    snapshots[1].save(update_fields=["config"])
    with override_settings(PUBLIC_INDEX=True):
        response = client.get("/public/", {"folder": str(folder.pk)}, HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    assert list(response.context["object_list"]) == [snapshots[0], snapshots[2]]
