"""Exercise the native Tags merge without touching live collection data."""

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from archivebox.api.models import OutboundWebhook
from archivebox.core.models import Folder, Snapshot, SnapshotTag, Tag
from archivebox.importers.models import ImporterSource
from archivebox.tests.conftest import ADMIN_TEST_HOST


@pytest.fixture
def merge_records(crawl):
    first = Tag.objects.create(name="Fixture first")
    second = Tag.objects.create(name="Fixture second")
    target = Tag.objects.create(name="Fixture target")
    other = Tag.objects.create(name="Fixture unrelated")
    snapshots = [Snapshot.objects.create(url=f"https://example.com/merge/{i}", crawl=crawl) for i in range(3)]
    snapshots[0].tags.set([first, second, target, other])
    snapshots[1].tags.set([first])
    snapshots[2].tags.set([second])
    return first, second, target, other, snapshots


def post_merge(client, tags, name, *, across=False, query=None, confirmed=True, expected_count=None):
    path = reverse("admin:core_tag_changelist")
    if query:
        path += f"?q={query}"
    return client.post(
        path,
        {
            "action": "merge_tags",
            "_selected_action": [tag.pk for tag in tags],
            "merge_tag_name": name,
            "confirm_tag_merge": "1" if confirmed else "",
            "confirm_tag_merge_count": str(len(tags) if expected_count is None else expected_count),
            "select_across": across if isinstance(across, str) else ("1" if across else "0"),
            "index": "0",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
        follow=True,
    )


@pytest.mark.django_db
def test_merge_deduplicates_reuses_target_within_selection(admin_client, merge_records):
    first, second, target, other, snapshots = merge_records
    before = set(Tag.objects.values_list("pk", flat=True))
    response = post_merge(admin_client, [first, second, target], target.name.lower())
    assert response.status_code == 200
    assert b"retired 2 tag(s); retained 3 Snapshot(s)" in response.content
    assert not Tag.objects.filter(pk__in=[first.pk, second.pk]).exists()
    assert set(Tag.objects.values_list("pk", flat=True)) == before - {first.pk, second.pk}
    assert Snapshot.objects.filter(pk__in=[snapshot.pk for snapshot in snapshots]).count() == 3
    assert SnapshotTag.objects.filter(tag=target).count() == 3
    assert snapshots[0].tags.filter(pk=other.pk).exists()


@pytest.mark.django_db
def test_merge_requires_confirmation_and_django_tag_permissions(client, django_user_model, merge_records):
    first, second, target, _other, _snapshots = merge_records
    user = django_user_model.objects.create_user("fixture-merger", is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=["view_tag", "change_tag"]))
    client.force_login(user)
    assert b"data-tag-merge-open" not in client.get(reverse("admin:core_tag_changelist"), HTTP_HOST=ADMIN_TEST_HOST).content
    assert b"Merged into" not in post_merge(client, [first, second], target.name).content
    user.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="delete_tag"))
    assert b"data-tag-merge-open" not in client.get(reverse("admin:core_tag_changelist"), HTTP_HOST=ADMIN_TEST_HOST).content
    assert b"Merged into" not in post_merge(client, [first, second], target.name).content
    assert Tag.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
    user.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="change_snapshot"))
    assert b"Confirm which tags" in post_merge(client, [first, second], target.name, confirmed=False).content
    assert b"do not have permission to create" in post_merge(client, [first, second], "Fixture new").content
    assert Tag.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
    assert b"Merged into" in post_merge(client, [first, second], target.name).content
    assert SnapshotTag.objects.filter(tag=target).count() == 3


@pytest.mark.django_db
def test_merge_blocks_active_tag_consumers_without_changing_any_rows(admin_client, admin_user, merge_records):
    first, second, target, _other, _snapshots = merge_records
    refs = [
        (
            "Smart Folder",
            Folder.objects.create(name="Fixture smart", rules={"field": "tags__name", "lookup": "istartswith", "value": "Fixture fir"}),
        ),
        (
            "Rule",
            OutboundWebhook.objects.create(
                ref="core.snapshot",
                signal="CREATE",
                actions=[{"type": "add_tags", "add_tags": first.name}],
                created_by=admin_user,
            ),
        ),
        (
            "Importer",
            ImporterSource.objects.create(
                name="Fixture importer",
                plugin="fixture",
                feed="fixture",
                tags=first.name,
                created_by=admin_user,
            ),
        ),
    ]
    for label, obj in refs:
        response = post_merge(admin_client, [first, second], "Fixture new")
        assert label.encode() in response.content and b"No tags were merged." in response.content
        assert not Tag.objects.filter(name="Fixture new").exists()
        assert SnapshotTag.objects.filter(tag=first).count() == 2
        obj.delete()
    response = post_merge(admin_client, [first, second], "Fixture new")
    created = Tag.objects.get(name="Fixture new")
    assert b"Merged into" in response.content
    assert SnapshotTag.objects.filter(tag=created).count() == 3
    assert SnapshotTag.objects.filter(tag=target).count() == 1


@pytest.mark.django_db
def test_merge_rejects_select_across_even_when_the_selected_count_matches(admin_client, merge_records):
    first, second, target, other, _snapshots = merge_records
    for tag in (first, second):
        tag.name = f"Subset {tag.name}"
        tag.save()
    # A same-size filtered result can replace the rows that were reviewed.
    for across in ("1", "true", "on"):
        response = post_merge(admin_client, [target, other], "Fixture new", across=across, query="Subset", expected_count=2)
        assert b"Select all matching tags is not supported" in response.content
    assert Tag.objects.filter(pk__in=[first.pk, second.pk, target.pk, other.pk]).count() == 4
    assert not Tag.objects.filter(name="Fixture new").exists()
    response = post_merge(admin_client, [first, second], "Fixture new", query="Subset")
    assert b"Merged into" in response.content
    assert Tag.objects.filter(pk__in=[target.pk, other.pk]).count() == 2
    assert not Tag.objects.filter(pk__in=[first.pk, second.pk]).exists()


@pytest.mark.django_db(transaction=True)
def test_merge_modal_cancel_and_confirm_from_real_tags_table(live_server, browser_runtime, admin_user, merge_records):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.machine.models import Machine

    first, second, target, _other, _snapshots = merge_records
    machine = Machine.current()
    machine.config.update(BASE_URL=live_server.url, SERVER_SECURITY_MODE="safe-onedomain-nojsreplay")
    machine.save(update_fields=["config"])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{live_server.url}/admin/login/?next={reverse('admin:core_tag_changelist')}")
        page.get_by_label("Username:", exact=True).fill(admin_user.username)
        page.get_by_label("Password:", exact=True).fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.get_by_role("row").filter(has_text=first.name).get_by_role("checkbox").check()
        opener = page.locator("[data-tag-merge-open]")
        expect(opener).to_be_disabled()
        page.get_by_role("row").filter(has_text=second.name).get_by_role("checkbox").check()
        expect(opener).to_be_enabled()
        opener.click()
        modal = page.get_by_role("dialog", name="Merge Tags")
        expect(modal).to_be_visible()
        expect(modal.locator("#tag-merge-count")).to_have_text("2")
        modal.get_by_role("button", name="Cancel").click()
        expect(modal).not_to_be_visible()
        expect(page.get_by_role("row").filter(has_text=first.name)).to_be_visible()
        opener.click()
        modal.get_by_label("Final tag name").fill(target.name)
        modal.get_by_role("button", name="Merge Tags", exact=True).click()
        expect(page.get_by_text(f'Merged into "{target.name}": retired 2 tag(s); retained 3 Snapshot(s).')).to_be_visible()
        browser.close()
    assert SnapshotTag.objects.filter(tag=target).count() == 3


@pytest.mark.django_db
def test_merge_uses_exact_case_and_name_not_numeric_tag_id(admin_client, merge_records):
    first, second, target, _other, _snapshots = merge_records
    exact = Tag.objects.create(name="Fixture Target")
    refusal = post_merge(admin_client, [first, second], "FIXTURE TARGET")
    assert b"different capitalization" in refusal.content
    assert Tag.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
    assert b"Merged into" in post_merge(admin_client, [first, second], exact.name).content
    assert SnapshotTag.objects.filter(tag=exact).count() == 3
    assert SnapshotTag.objects.filter(tag=target).count() == 1
    assert b"Merged into" in post_merge(admin_client, [exact, target], str(exact.pk)).content
    assert SnapshotTag.objects.filter(tag__name=str(exact.pk)).count() == 3


@pytest.mark.django_db
def test_merge_blocks_enabled_schedule_and_active_crawl(admin_client, admin_user, crawl, merge_records):
    from archivebox.crawls.models import Crawl, CrawlSchedule

    first, second, target, _other, _snapshots = merge_records
    template = Crawl.objects.create(
        urls="https://example.com",
        tags_str=first.name,
        created_by=admin_user,
        status=Crawl.StatusChoices.PAUSED,
    )
    schedule = CrawlSchedule.objects.create(template=template, schedule="daily", created_by=admin_user)
    response = post_merge(admin_client, [first, second], target.name)
    assert b"Update Scheduled Crawl" in response.content
    schedule.is_enabled = False
    schedule.save(update_fields=["is_enabled"])
    assert b"Wait for Crawl" in post_merge(admin_client, [first, second], target.name).content
    template.status = Crawl.StatusChoices.SEALED
    template.save(update_fields=["status"])
    crawl.tags_str = first.name
    crawl.status = Crawl.StatusChoices.QUEUED
    crawl.save(update_fields=["tags_str", "status"])
    assert b"Wait for Crawl" in post_merge(admin_client, [first, second], target.name).content
    crawl.status = Crawl.StatusChoices.PAUSED
    crawl.save(update_fields=["status"])
    assert b"Wait for Crawl" in post_merge(admin_client, [first, second], target.name).content
    crawl.status = Crawl.StatusChoices.SEALED
    crawl.save(update_fields=["status"])
    assert b"Merged into" in post_merge(admin_client, [first, second], target.name).content


@pytest.mark.django_db(transaction=True)
def test_merge_bounds_snapshot_links_and_runs_in_bulk(admin_user, crawl):
    from time import perf_counter

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from archivebox.core.tag_merge import MERGE_MAX_LINKS, merge_selected_tags

    first, second = (Tag.objects.create(name=f"Fixture bulk {i}") for i in range(2))
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(url=f"https://example.com/bulk-merge/{i}", crawl=crawl, timestamp=f"1950000000.{i:06}")
            for i in range(MERGE_MAX_LINKS + 1)
        ],
    )
    links = SnapshotTag.objects.bulk_create(
        [SnapshotTag(tag=first if i % 2 else second, snapshot=snapshot) for i, snapshot in enumerate(snapshots)],
    )
    selection = Tag.objects.filter(pk__in=[first.pk, second.pk])
    with pytest.raises(ValueError, match="over 2,500 Snapshot links"):
        merge_selected_tags(
            selection,
            "Fixture cap target",
            user=admin_user,
            can_create=True,
            selected_count="2",
            snapshot_scope=Snapshot.objects.all(),
        )
    assert selection.count() == 2
    assert not Tag.objects.filter(name="Fixture cap target").exists()
    SnapshotTag.objects.filter(pk=links[-1].pk).delete()
    t0 = perf_counter()
    with CaptureQueriesContext(connection) as queries:
        target, retired, changed = merge_selected_tags(
            selection,
            "Fixture cap target",
            user=admin_user,
            can_create=True,
            selected_count="2",
            snapshot_scope=Snapshot.objects.all(),
        )
    elapsed = (perf_counter() - t0) * 1000
    print(f"SQLite merge at {MERGE_MAX_LINKS:,} links: {elapsed:.1f}ms, {len(queries)} SQL statements incl. commit")
    association_inserts = [q for q in queries if q["sql"].startswith('INSERT INTO "core_snapshot_tags"')]
    assert 1 <= len(association_inserts) <= 8
    assert len(queries) < 64
    assert (retired, changed) == (2, MERGE_MAX_LINKS)
    assert target.snapshot_set.count() == MERGE_MAX_LINKS
    assert Snapshot.objects.filter(pk__in=[item.pk for item in snapshots]).count() == MERGE_MAX_LINKS + 1


@pytest.mark.django_db
def test_merge_rejects_over_cap_explicit_selection(admin_client):
    tags = Tag.objects.bulk_create([Tag(name=f"Fixture cap {i}") for i in range(51)])
    response = post_merge(admin_client, tags, "Fixture new")
    assert b"Select between 2 and 50 tags" in response.content
    assert Tag.objects.filter(pk__in=[tag.pk for tag in tags]).count() == 51
    assert not Tag.objects.filter(name="Fixture new").exists()


@pytest.mark.django_db
def test_merge_refuses_partial_snapshot_scope(admin_user, merge_records):
    from archivebox.core.tag_merge import merge_selected_tags

    first, second, target, _other, snapshots = merge_records
    with pytest.raises(ValueError, match="outside your permissions"):
        merge_selected_tags(
            Tag.objects.filter(pk__in=[first.pk, second.pk]),
            target.name,
            user=admin_user,
            can_create=True,
            selected_count="2",
            snapshot_scope=Snapshot.objects.exclude(pk=snapshots[1].pk),
        )
    assert Tag.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
    assert SnapshotTag.objects.filter(tag=target).count() == 1


@pytest.mark.django_db
def test_merge_blocks_encoded_importer_tag_reference(admin_client, admin_user, merge_records):
    first, second, target, _other, _snapshots = merge_records
    first.name = "Fixture Foo & Bar"
    first.save(update_fields=["name"])
    ImporterSource.objects.create(
        name="Fixture importer",
        plugin="fixture",
        feed="fixture",
        tags="Fixture Foo &amp; Bar",
        created_by=admin_user,
    )
    assert b"Update Importer" in post_merge(admin_client, [first, second], target.name).content
    assert Tag.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
    assert SnapshotTag.objects.filter(tag=target).count() == 1


@pytest.mark.django_db(transaction=True)
def test_merge_rolls_back_after_real_sqlite_delete_failure(admin_user, merge_records):
    from django.db import IntegrityError, connection

    from archivebox.core.tag_merge import merge_selected_tags

    first, second, _target, _other, _snapshots = merge_records
    all_tags = set(Tag.objects.values_list("pk", flat=True))
    all_links = set(SnapshotTag.objects.values_list("snapshot_id", "tag_id"))
    # A real DB constraint failure after writing the destination must revert
    # both the destination row and all new association inserts.
    table = connection.ops.quote_name(Tag._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE TEMP TRIGGER fixture_reject_tag_merge BEFORE DELETE ON {table} "
            f"WHEN OLD.id = {int(first.pk)} BEGIN SELECT RAISE(ABORT, 'fixture merge delete rejected'); END",
        )
    try:
        with pytest.raises(IntegrityError, match="fixture merge delete rejected"):
            merge_selected_tags(
                Tag.objects.filter(pk__in=[first.pk, second.pk]),
                "Fixture should roll back",
                user=admin_user,
                can_create=True,
                selected_count="2",
                snapshot_scope=Snapshot.objects.all(),
            )
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER fixture_reject_tag_merge")
    assert set(Tag.objects.values_list("pk", flat=True)) == all_tags
    assert set(SnapshotTag.objects.values_list("snapshot_id", "tag_id")) == all_links


@pytest.mark.django_db
@pytest.mark.parametrize(("signal", "relationship"), [("M2M_ADD", ""), ("M2M_REMOVE", "tags")])
def test_merge_blocks_reachable_snapshot_tag_relationship_rules(admin_client, admin_user, merge_records, signal, relationship):
    first, second, target, _other, snapshots = merge_records
    OutboundWebhook.objects.create(
        ref="core.snapshot",
        signal=signal,
        relationship=relationship,
        created_by=admin_user,
    )
    response = post_merge(admin_client, [first, second], target.name)
    assert b"it acts on Snapshot tag changes" in response.content
    assert Tag.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
    assert SnapshotTag.objects.filter(tag=target).count() == 1
    if signal == "M2M_ADD":
        # Adding nothing would not fire an M2M_ADD rule; removal-only merges
        # are allowed when no relevant remove Rule exists.
        SnapshotTag.objects.create(snapshot=snapshots[1], tag=target)
        SnapshotTag.objects.create(snapshot=snapshots[2], tag=target)
        assert b"Merged into" in post_merge(admin_client, [first, second], target.name).content
