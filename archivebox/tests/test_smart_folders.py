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


@pytest.mark.filterwarnings("error:DateTimeField .* received a naive datetime:RuntimeWarning")
@pytest.mark.parametrize("value", ["2026-01-01", "2026-01-01T00:00:00", "2026-01-01T01:00:00+01:00"])
def test_date_rules_use_timezone_aware_boundaries(admin_user, value):
    from datetime import datetime, timezone

    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    before = Snapshot.objects.create(
        url="https://example.com/before",
        crawl=crawl,
        bookmarked_at=datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
    )
    after = Snapshot.objects.create(url="https://example.com/after", crawl=crawl, bookmarked_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    for lookup in ("gte", "exact"):
        rule = leaf("bookmarked_at", lookup, value)
        folder = Folder.objects.create(name=f"Dates {lookup}", rules=rule)
        assert list(Folder.select_snapshots(Snapshot.objects.all(), folder.pk)) == [after]
        assert not Folder.select_snapshots(Snapshot.objects.all(), folder.pk).filter(pk=before.pk).exists()


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


def test_folder_type_is_immutable_and_nonempty_admin_delete_is_blocked(admin_client, admin_user):
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
    assert response.status_code == 409, response.content
    snapshot.refresh_from_db()
    assert snapshot.folder_id == manual.pk
    assert Folder.objects.filter(pk=manual.pk).exists()


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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("new_kind", ["Rule", "Group"])
def test_browser_append_to_full_root_preserves_existing_expression(live_server, admin_user, browser_runtime, new_kind):
    import json
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
    original = group("NOT", group("OR", leaf("title", "exact", "A"), leaf("title", "exact", "B")))
    folder = Folder.objects.create(name="Full root", rules=original)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        row = page.locator(f'.folder-row[data-folder-id="{folder.pk}"]')
        row.hover()
        row.get_by_role("button", name="Actions for Full root", exact=True).click()
        row.get_by_role("menuitem", name="Rename", exact=True).click()
        expect(page.locator(".folder-save")).to_be_enabled()
        root = page.locator(".folder-rules > .rule-group")
        root.locator(":scope > .rule-group-toolbar").get_by_role("button", name=f"+ {new_kind}", exact=True).click()
        root.locator(".rule-value input").last.fill("archive")
        if new_kind == "Group":
            child = root.locator(":scope > .rule-group").last
            child.locator(":scope > .rule-group-toolbar").get_by_role("button", name="+ Rule", exact=True).click()
            child.locator(".rule-value input").last.fill("saved")
            added = group("AND", leaf("url", "icontains", "archive"), leaf("url", "icontains", "saved"))
        else:
            added = leaf("url", "icontains", "archive")
        expected = group("AND", original, added)
        assert json.loads(page.locator('input[name="rules"]').input_value()) == expected
        expect(root.locator(":scope > .rule-group-toolbar").get_by_role("button", name="+ Rule", exact=True)).to_be_visible()
        expect(root.locator(":scope > .rule-group-toolbar").get_by_role("button", name="+ Group", exact=True)).to_be_visible()
        page.locator(".folder-save").click()
        expect(page.locator("#folder-dialog")).not_to_be_visible()
        browser.close()
    folder.refresh_from_db()
    assert folder.rules == expected


def test_smart_folder_preview_permissions_order_limits_and_no_writes(admin_client, admin_user, client, django_user_model):
    import json
    from django.contrib.auth.models import Permission
    from django.urls import reverse
    from archivebox.tests.conftest import ADMIN_TEST_HOST

    route = reverse("admin:core_folder_rules")
    host = {"HTTP_HOST": ADMIN_TEST_HOST}
    crawl = Crawl.objects.create(urls="https://example.org/", created_by=admin_user)
    for title in ("Zulu", "Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Eta"):
        Snapshot.objects.create(url=f"https://example.org/{title}", title=title, crawl=crawl)
    original = leaf("title", "exact", "Alpha")
    folder = Folder.objects.create(name="Saved", rules=original)
    proposed = {
        **group("AND", leaf("url", "icontains", "example.org"), group("NOT", leaf("title", "exact", "Beta"))),
        "sort": "-title",
        "limit": 2,
    }
    data = {"folder_id": str(folder.pk), "rules": json.dumps(proposed)}
    response = admin_client.post(route, data, **host)
    assert response.status_code == 200, response.content
    assert [row["title"] for row in response.json()["snapshots"]] == ["Zulu", "Gamma"]
    folder.refresh_from_db()
    assert folder.rules == original

    folders_before = set(Folder.objects.values_list("pk", flat=True))
    data = {"rules": json.dumps({**leaf("url", "icontains", "example.org"), "limit": 2000})}
    assert len(admin_client.post(route, data, **host).json()["snapshots"]) == 6
    assert set(Folder.objects.values_list("pk", flat=True)) == folders_before
    assert admin_client.post(route, {"rules": "[]"}, **host).status_code == 400

    staff = django_user_model.objects.create_user(username="folder-editor", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="add_folder"))
    client.force_login(staff)
    assert client.post(route, data, **host).status_code == 403
    staff.user_permissions.add(Permission.objects.get(codename="view_snapshot"))
    assert client.post(route, data, **host).status_code == 200
    assert client.post(route, {**data, "folder_id": str(folder.pk)}, **host).status_code == 403


def test_folder_preview_windows_preserve_order_and_limit_across_sparse_matches(admin_user):
    from archivebox.core.admin_folders import _preview_page

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://news.ycombinator.com/item?id={i}",
                timestamp=str(1800000000 + i),
                title=f"{i:04}",
                crawl=crawl,
            )
            for i in range(1034)
        ],
        batch_size=100,
    )
    base = Snapshot.objects.filter(crawl=crawl)
    # With only one match in the first full window, its continuation must
    # advance past the non-matches while retaining the remaining row allowance.
    matching = [snapshots[i].pk for i in (1024, 1026, 1027, 1033)]
    matches = base.filter(pk__in=matching)
    ids, after = _preview_page(base, matches, ["title", "pk"], 3, (1, 1024))
    assert ids == matching[:1]
    assert after == (1025, 1024)
    # A real intervening insert shifts a returned row onto the next page.
    # The signed cursor's displayed IDs leave room for the missing match.
    Snapshot.objects.create(crawl=crawl, url="https://news.ycombinator.com/newest", title="0000a")
    assert _preview_page(base, matches, ["title", "pk"], 2, after, [matching[0].hex]) == (matching[1:3], None)

    # The candidate order and the final filtered order use the same null
    # placement and PK tiebreaker, including the UUID-seeded shuffle.
    for sort in ("bookmarked_at", "-bookmarked_at", "?"):
        ordering = RuleQuery.ordering(Folder(rules={"sort": sort}))
        expected = [pk for pk in base.order_by(*ordering).values_list("pk", flat=True)[1:] if pk in matching]
        ids, after = _preview_page(base, matches, ordering, 6, (1, 1024))
        if after is not None:
            tail, after = _preview_page(base, matches, ordering, 6 - len(ids), after)
            ids += tail
        assert after is None
        assert ids == expected


@pytest.mark.django_db(transaction=True)
def test_browser_smart_folder_preview_updates_without_saving(live_server, admin_user, request):
    import os
    from pathlib import Path
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
    crawl = Crawl.objects.create(urls="https://example.org/", created_by=admin_user)
    tag = Tag.objects.create(name="reading")
    for domain, title, is_tagged in (
        ("docs.example.org", "Designing resilient background jobs", True),
        ("journal.example.org", "A practical guide to database indexes", True),
        ("notes.example.org", "SQLite write-ahead logging in practice", True),
        ("lab.example.org", "Browser performance measurements", False),
    ):
        snapshot = Snapshot.objects.create(url=f"https://{domain}/", title=title, crawl=crawl)
        if is_tagged:
            snapshot.tags.add(tag)
    original = {**group("AND", leaf("url", "icontains", "example.org"), leaf("tags__name", "exact", "reading")), "limit": 5}
    folder = Folder.objects.create(name="Reading list", rules=original)
    with sync_playwright() as playwright:
        exe = os.environ.get("ARCHIVEBOX_REVIEW_BROWSER")
        runtime = request.getfixturevalue("browser_runtime") if not exe else None
        browser = playwright.chromium.launch(
            executable_path=exe or str(runtime["chrome_binary"]),
            args=runtime["chrome_args"] if runtime else ["--disable-background-networking"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        row = page.locator(f'.folder-row[data-folder-id="{folder.pk}"]')
        row.hover()
        row.get_by_role("button", name="Actions for Reading list", exact=True).click()
        row.get_by_role("menuitem", name="Rename", exact=True).click()
        dialog = page.locator("#folder-dialog")
        matches = dialog.locator(".folder-match")
        expect(matches).to_have_count(3)
        expect(dialog.get_by_role("heading", name="Search", exact=True)).to_be_visible()
        expect(dialog.get_by_text("Advanced rules", exact=True)).to_be_visible()
        desktop = dialog.locator(".folder-rule-panel").bounding_box()
        desktop_preview = dialog.locator(".folder-match-panel").bounding_box()
        assert desktop["x"] + desktop["width"] < desktop_preview["x"]
        option = dialog.get_by_label("Sort by", exact=True).bounding_box()
        assert abs(dialog.get_by_label("Name", exact=True).bounding_box()["y"] - option["y"]) <= 1

        if output := os.environ.get("ARCHIVEBOX_REVIEW_SCREENSHOTS"):
            dialog.screenshot(path=Path(output) / "smart-folder-desktop.png")
        page.set_viewport_size({"width": 390, "height": 844})
        expect(matches).to_have_count(3)
        mobile = dialog.locator(".folder-rule-panel").bounding_box()
        mobile_preview = dialog.locator(".folder-match-panel").bounding_box()
        assert mobile["y"] + mobile["height"] < mobile_preview["y"]
        assert dialog.evaluate("(el) => el.scrollWidth <= el.clientWidth")
        assert dialog.locator(".folder-rule-layout").evaluate("(el) => el.scrollWidth <= el.clientWidth")
        if output:
            page.set_viewport_size({"width": 390, "height": 1040})
            dialog.screenshot(path=Path(output) / "smart-folder-mobile.png")
            page.set_viewport_size({"width": 390, "height": 844})
        dialog.get_by_label("Limit", exact=True).fill("1")
        expect(matches).to_have_count(1)
        dialog.get_by_label("Value", exact=True).last.fill("missing")
        expect(dialog.get_by_text("No matching snapshots.")).to_be_visible()
        page.context.set_offline(True)
        dialog.get_by_label("Value", exact=True).last.fill("reading")
        retry = dialog.get_by_role("button", name="Retry")
        expect(retry).to_be_visible()
        page.context.set_offline(False)
        retry.click()
        expect(matches).to_have_count(1)
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).not_to_be_visible()
        browser.close()
    folder.refresh_from_db()
    assert folder.rules == original


def test_search_rule_uses_snapshot_query_and_preserves_advanced_conditions(crawl):
    from archivebox.search.interpreter import SnapshotSearch

    first = Snapshot.objects.create(crawl=crawl, url="https://example.org/a", title="ABC:DEF solar")
    second = Snapshot.objects.create(crawl=crawl, url="https://example.org/b", title="Solar atlas")
    other = Snapshot.objects.create(crawl=crawl, url="https://example.org/0", title="unrelated")
    tag = Tag.objects.create(name="solar-research")
    first.tags.add(tag)
    second.tags.add(tag)
    query = 'tag:solar AND (title:"ABC:DEF" OR title:atlas)'
    rule = group("NOT", leaf("url", "exact", first.url))
    folder = Folder.objects.create(name="Reading", rules={**rule, "query": query, "sort": "url", "limit": 1})
    assert set(SnapshotSearch(Snapshot.objects.all(), query).queryset()) == {first, second}
    assert list(Snapshot.objects.in_folder(folder.pk)) == [second]
    folder.refresh_from_db()
    assert folder.rules == {**rule, "query": query, "sort": "url", "limit": 1}
    other.tags.add(tag)
    other.title = "Western atlas"
    other.save(update_fields=["title"])
    folder.rules["sort"] = "title"
    folder.save()
    assert list(Snapshot.objects.in_folder(folder.pk)) == [second]
    folder.rules["sort"] = "-title"
    folder.save()
    assert list(Snapshot.objects.in_folder(folder.pk)) == [other]


def test_folder_search_rejects_uncertain_membership_and_recursive_references():
    folder = Folder.objects.create(name="Rules", rules=leaf("title", "icontains", "needle"))
    for query, message in [
        ('~deep:"missing"', "complete membership"),
        ("(tags:missing", "closing parenthesis"),
        (f"folder__in_folder:{folder.pk}", "cycle"),
    ]:
        folder.rules = {"query": query}
        with pytest.raises(ValidationError, match=message):
            folder.save()
        folder.refresh_from_db()
        assert folder.rules == leaf("title", "icontains", "needle")


def test_typed_builder_lookups_in_search_queries(crawl):
    import json

    from archivebox.core.models import ArchiveResult
    from archivebox.search.interpreter import SnapshotSearch

    matched = Snapshot.objects.create(crawl=crawl, url="https://example.org/match", title="Red, blue")
    Snapshot.objects.create(crawl=crawl, url="https://example.org/other", title="Red")
    files = {"index.txt": {"size": 3}}
    ArchiveResult.objects.create(snapshot=matched, plugin="title", output_size=1_050_000, status="succeeded", output_files=files)
    for rule, text in [
        (leaf("title", "in", ["Red, blue", "Green"]), json.dumps(["Red, blue", "Green"])),
        (leaf("archiveresult__output_files", "exact", files), json.dumps(files)),
        (leaf("archiveresult__output_size", "gte", {"amount": 1, "unit": "MB"}), "1 MB"),
    ]:
        query = f"{rule['field']}__{rule['lookup']}:{json.dumps(text)}"
        assert list(Snapshot.objects.filter(RuleQuery().compile(rule))) == [matched], rule
        assert list(SnapshotSearch(Snapshot.objects.all(), query).queryset()) == [matched], query


@pytest.mark.django_db(transaction=True)
def test_new_smart_folder_starts_with_search_and_saves_advanced_rules(browser_runtime, live_server, admin_user, crawl):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.smart_folders import CHILDREN_RULES
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    panel = Snapshot.objects.create(crawl=crawl, url="https://energy.example.org/panels", title="Solar Panel Field Guide")
    atlas = Snapshot.objects.create(crawl=crawl, url="https://energy.example.org/atlas", title="Community Solar Atlas")
    tag = Tag.objects.create(name="solar-research")
    panel.tags.add(tag)
    atlas.tags.add(tag)
    query = 'tags:solar AND (title:"Solar Panel" OR title:Atlas)'
    parent = Folder.objects.create(name="Permissions", rules=CHILDREN_RULES)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(live_server.url.replace("localhost", "admin.archivebox.localhost") + "/admin/login/?next=/admin/core/snapshot/")
        page.get_by_label("Username").fill(admin_user.username)
        page.get_by_label("Password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        parent_row = page.locator(f'.folder-row[data-folder-id="{parent.pk}"]')
        dialog = page.locator("#folder-dialog")
        for label in ("New folder", "New smart folder"):
            parent_row.hover()
            page.get_by_role("button", name="Add folder in Permissions", exact=True).click()
            parent_row.get_by_role("menuitem", name=label, exact=True).click()
            expect(dialog.get_by_role("heading", name=label, exact=True)).to_be_visible()
            expect(dialog.locator("#folder-parent")).to_have_value(str(parent.pk))
            page.keyboard.press("Escape")
            expect(dialog).not_to_be_visible()
        page.get_by_role("button", name="Create folder", exact=True).click()
        page.get_by_role("menuitem", name="New smart folder", exact=True).click()
        expect(dialog.locator(".folder-save")).to_be_enabled()
        expect(dialog.locator(".folder-advanced")).not_to_have_attribute("open", "")
        dialog.get_by_label("Name", exact=True).fill("Energy")
        editor = dialog.get_by_role("combobox", name="Search snapshots")
        for width, height in ((1400, 900), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            editor.click()
            option = dialog.get_by_role("option", name="url:", exact=False)
            # Visibility alone passes for a clipped child. Hit-test its center
            # before Playwright can scroll the entire rules pane on our behalf.
            expect(option).to_be_visible()
            assert option.evaluate("""el => {
                const {x, y, width, height} = el.getBoundingClientRect();
                return el.contains(document.elementFromPoint(x + width / 2, y + height / 2));
            }"""), (width, height)
            option.click()
            expect(dialog.locator('input[name="folder_query"]')).to_have_value("url:")
            editor.fill("")
            editor.press("Escape")
            dialog.get_by_label("Name", exact=True).click()
        editor.fill(query)
        expect(dialog.locator(".folder-match")).to_have_count(2)
        dialog.locator("summary").click()
        dialog.get_by_role("button", name="+ Rule", exact=True).click()
        dialog.get_by_label("Field", exact=True).select_option("title")
        dialog.get_by_label("Comparison", exact=True).select_option("icontains")
        dialog.get_by_role("textbox", name="Value", exact=True).fill("Panel")
        dialog.get_by_label("Sort by", exact=True).select_option("title")
        dialog.get_by_label("Sort direction", exact=True).select_option("asc")
        dialog.get_by_label("Limit", exact=True).fill("1")
        expect(dialog.locator(".folder-match strong")).to_have_text(panel.title)
        dialog.get_by_role("button", name="Save folder").click()
        expect(dialog).not_to_be_visible()
        browser.close()
    folder = Folder.objects.get(name="Energy")
    assert folder.rules == {**leaf("title", "icontains", "Panel"), "query": query, "sort": "title", "limit": 1}
    assert list(Snapshot.objects.in_folder(folder.pk)) == [panel]
