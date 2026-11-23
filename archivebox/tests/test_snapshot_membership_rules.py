"""Exercise Snapshot membership rules through the editor and real mutations."""

import json
from pathlib import Path

import pytest
from django.db import transaction
from django.urls import reverse

from archivebox.api.models import OutboundWebhook
from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST, api_client_request
from archivebox.tests.test_webhook_views import post, webhook_input

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def membership_rules(admin_client, tmp_path):
    def subscribe(signal, **scope):
        path = tmp_path / f"deliveries-{len(list(tmp_path.glob('deliveries-*')))}.jsonl"
        path.touch()
        code = f"import sys, pathlib\nwith pathlib.Path({str(path)!r}).open('a') as out: out.write(sys.stdin.read() + '\\n')"
        response = post(
            admin_client,
            "save/",
            webhook_input(name=f"{signal} {path.stem}", signal=signal, enabled=True, actions=[dict(type="python", code=code)], **scope),
        )
        assert response.status_code == 200, response.content
        return path

    return subscribe


def deliveries(path: Path, scope):
    return [(row["event"], row["id"], row[scope]) for row in map(json.loads, path.read_text().splitlines())]


def test_specific_tag_and_any_tag_match_actual_api_changes(client, api_admin_user, api_headers, membership_rules):
    research = Tag.objects.create(name="Research")
    other = Tag.objects.create(name="Other")
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    tagged = membership_rules("TAGGED", tag_id=research.pk)
    untagged = membership_rules("UNTAGGED", tag_id=research.pk)
    any_tagged = membership_rules("TAGGED", tag_id="*")
    any_untagged = membership_rules("UNTAGGED", tag_id="*")
    legacy = membership_rules("M2M_REMOVE", relationship="tags")

    def edit(action, tag):
        response = api_client_request(
            client,
            "post",
            f"/api/v1/core/tags/{action}-snapshot/",
            payload={"snapshot_id": str(snapshot.pk), "tag_id": tag.pk},
            headers=api_headers,
        )
        assert response.status_code == 200, response.content

    edit("add-to", other)
    edit("add-to", research)
    edit("add-to", research)
    assert set(snapshot.tags.values_list("pk", flat=True)) == {research.pk, other.pk}
    response = api_client_request(
        client,
        "post",
        f"/api/v1/core/tag/{research.pk}/rename",
        payload={"name": "Reading"},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content
    edit("remove-from", other)
    edit("remove-from", other)
    edit("remove-from", research)
    assert not snapshot.tags.exists()

    sid = str(snapshot.pk)
    assert deliveries(tagged, "tag_id") == [("TAGGED", sid, research.pk)]
    assert deliveries(untagged, "tag_id") == [("UNTAGGED", sid, research.pk)]
    assert deliveries(any_tagged, "tag_id") == [("TAGGED", sid, other.pk), ("TAGGED", sid, research.pk)]
    assert deliveries(any_untagged, "tag_id") == [("UNTAGGED", sid, other.pk), ("UNTAGGED", sid, research.pk)]
    assert [row["tag_name"] for row in map(json.loads, untagged.read_text().splitlines())] == ["Reading"]
    assert deliveries(legacy, "relationship") == [("M2M_REMOVE", sid, "tags")] * 2


def test_tag_replacement_clear_reverse_edits_and_rollback(client, api_admin_user, api_headers, membership_rules):
    first, second, third = (Tag.objects.create(name=name) for name in ("First", "Second", "Third"))
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    snapshot.tags.add(first, second)
    added = membership_rules("TAGGED", tag_id="*")
    removed = membership_rules("UNTAGGED", tag_id="*")
    legacy_clear = membership_rules("M2M_CLEAR", relationship="tags")

    response = api_client_request(
        client,
        "patch",
        f"/api/v1/core/snapshot/{snapshot.pk}",
        payload={"tags": [second.name, third.name]},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content
    assert set(snapshot.tags.values_list("pk", flat=True)) == {second.pk, third.pk}
    assert not legacy_clear.read_text()
    with pytest.raises(ValueError, match="undo removal"):
        with transaction.atomic():
            assert snapshot.remove_tag_ids([second.pk]) == 1
            assert not snapshot.tags.filter(pk=second.pk).exists()
            raise ValueError("undo removal")
    assert set(snapshot.tags.values_list("pk", flat=True)) == {second.pk, third.pk}
    snapshot.tags.clear()
    assert not snapshot.tags.exists()
    first.snapshot_set.add(snapshot)
    first.snapshot_set.add(snapshot)
    first.snapshot_set.remove(snapshot)
    first.snapshot_set.remove(snapshot)
    with pytest.raises(ValueError, match="undo tag"):
        with transaction.atomic():
            snapshot.tags.add(first)
            raise ValueError("undo tag")

    assert not snapshot.tags.exists()
    sid = str(snapshot.pk)
    assert deliveries(added, "tag_id") == [("TAGGED", sid, third.pk), ("TAGGED", sid, first.pk)]
    assert sorted(deliveries(removed, "tag_id")) == sorted(
        [
            ("UNTAGGED", sid, first.pk),
            ("UNTAGGED", sid, second.pk),
            ("UNTAGGED", sid, third.pk),
            ("UNTAGGED", sid, first.pk),
        ],
    )
    assert deliveries(legacy_clear, "relationship") == [("M2M_CLEAR", sid, "tags")]


def test_bulk_admin_edits_trigger_tag_and_smart_folder_rules_once(admin_client, admin_user, membership_rules):
    tag = Tag.objects.create(name="Research")
    smart = Folder.objects.create(name="Smart research", rules={"field": "tags__name", "lookup": "exact", "value": tag.name})
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    snapshots = [Snapshot.objects.create(url=f"https://example.com/{i}", crawl=crawl) for i in range(2)]
    snapshots[0].tags.add(tag)
    tagged = membership_rules("TAGGED", tag_id=tag.pk)
    untagged = membership_rules("UNTAGGED", tag_id=tag.pk)
    entered = membership_rules("FOLDER_ENTERED", folder_id=str(smart.pk))
    left = membership_rules("FOLDER_LEFT", folder_id=str(smart.pk))

    for action in ("add_tags", "add_tags", "remove_tags", "remove_tags"):
        response = admin_client.post(
            reverse("admin:core_snapshot_changelist"),
            {"action": action, "tags": tag.name, "_selected_action": [str(snapshot.pk) for snapshot in snapshots], "index": "0"},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 302, response.content

    assert not tag.snapshot_set.exists()
    assert not Snapshot.objects.in_folder(smart.pk).exists()
    assert deliveries(tagged, "tag_id") == [("TAGGED", str(snapshots[1].pk), tag.pk)]
    assert deliveries(entered, "folder_id") == [("FOLDER_ENTERED", str(snapshots[1].pk), str(smart.pk))]
    assert sorted(deliveries(untagged, "tag_id")) == sorted(("UNTAGGED", str(snapshot.pk), tag.pk) for snapshot in snapshots)
    assert sorted(deliveries(left, "folder_id")) == sorted(("FOLDER_LEFT", str(snapshot.pk), str(smart.pk)) for snapshot in snapshots)


def test_deleting_tag_delivers_any_tag_rule_and_retires_specific_rule(client, api_admin_user, api_headers, membership_rules):
    tag = Tag.objects.create(name="Retired tag")
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    snapshot.tags.add(tag)
    untagged = membership_rules("UNTAGGED", tag_id="*")
    membership_rules("UNTAGGED", tag_id=tag.pk)
    specific_rule = OutboundWebhook.objects.get(signal="UNTAGGED", relationship=str(tag.pk))
    response = api_client_request(client, "delete", f"/api/v1/core/tag/{tag.pk}", headers=api_headers)
    assert response.status_code == 200, response.content
    assert not snapshot.tags.exists()
    assert not OutboundWebhook.objects.filter(pk=specific_rule.pk).exists()
    assert deliveries(untagged, "tag_id") == [("UNTAGGED", str(snapshot.pk), tag.pk)]
    assert json.loads(untagged.read_text())["tag_name"] == "Retired tag"


def test_tag_rules_run_native_actions_without_recursive_delivery(admin_client, client, api_admin_user, api_headers, membership_rules):
    tag = Tag.objects.create(name="Research")
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    wildcard = membership_rules("TAGGED", tag_id="*")
    rule = post(
        admin_client,
        "save/",
        webhook_input(signal="TAGGED", tag_id=tag.pk, enabled=True, actions=[{"type": "add_tags", "add_tags": "Reviewed"}]),
    )
    assert rule.status_code == 200, rule.content
    response = api_client_request(
        client,
        "post",
        "/api/v1/core/tags/add-to-snapshot/",
        payload={"snapshot_id": str(snapshot.pk), "tag_id": tag.pk},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content
    assert set(snapshot.tags.values_list("name", flat=True)) == {"Research", "Reviewed"}
    assert deliveries(wildcard, "tag_id") == [("TAGGED", str(snapshot.pk), tag.pk)]
    assert OutboundWebhook.objects.get(pk=rule.json()["hook"]["id"]).num_uses_succeeded == 1


def test_discovered_snapshot_tags_trigger_tag_and_folder_rules(admin_user, membership_rules):
    inherited = Tag.objects.create(name="Inherited")
    discovered = Tag.objects.create(name="Discovered")
    smart = Folder.objects.create(name="Discovered items", rules={"field": "tags__name", "lookup": "exact", "value": discovered.name})
    crawl = Crawl.objects.create(urls="https://example.com/", max_depth=1, tags_str=inherited.name, created_by=admin_user)
    parent = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    entered = membership_rules("FOLDER_ENTERED", folder_id=str(smart.pk))
    tagged = membership_rules("TAGGED", tag_id="*")

    children = crawl.create_discovered_snapshots(
        parent,
        [{"url": "https://example.com/child", "tags": f"{inherited.name},{discovered.name}"}],
        depth=1,
    )
    assert len(children) == 1
    child = children[0]
    assert set(child.tags.values_list("pk", flat=True)) == {inherited.pk, discovered.pk}
    assert deliveries(tagged, "tag_id") == [("TAGGED", str(child.pk), tag.pk) for tag in (inherited, discovered)]
    assert deliveries(entered, "folder_id") == [("FOLDER_ENTERED", str(child.pk), str(smart.pk))]


@pytest.mark.parametrize("scope", ["retired", "wildcard"])
def test_merge_protects_rules_that_depend_on_changed_tags(admin_client, admin_user, membership_rules, scope):
    from archivebox.tests.test_tag_merge import post_merge

    retired = Tag.objects.create(name="Retired")
    target = Tag.objects.create(name="Target")
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    snapshot.tags.add(retired)
    path = membership_rules("TAGGED", tag_id=retired.pk if scope == "retired" else "*")

    response = post_merge(admin_client, [retired, target], target.name)
    assert response.status_code == 200
    assert b"No tags were merged." in response.content
    assert Tag.objects.filter(pk=retired.pk).exists()
    assert list(snapshot.tags.values_list("pk", flat=True)) == [retired.pk]
    assert not path.read_text()


def test_folder_api_move_emits_membership_deltas_for_child_and_parent(client, api_admin_user, api_headers, membership_rules):
    parent = Folder.objects.create(name="Parent")
    first, second = (Folder.objects.create(name=name, parent=parent) for name in ("First", "Second"))
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    entered = membership_rules("FOLDER_ENTERED", folder_id="*")
    left = membership_rules("FOLDER_LEFT", folder_id=str(parent.pk))

    for folder in (first, first, second, None):
        response = api_client_request(
            client,
            "post",
            "/api/v1/core/folders/move-snapshots",
            payload={"snapshot_ids": [str(snapshot.pk)], "destination_id": str(folder.pk) if folder else None},
            headers=api_headers,
        )
        assert response.status_code == 200, response.content
        snapshot.refresh_from_db()
        assert snapshot.folder_id == (folder.pk if folder else None)

    sid = str(snapshot.pk)
    assert sorted(deliveries(entered, "folder_id")) == sorted(("FOLDER_ENTERED", sid, str(folder.pk)) for folder in (parent, first, second))
    assert deliveries(left, "folder_id") == [("FOLDER_LEFT", sid, str(parent.pk))]


@pytest.mark.parametrize("signal", ["TAGGED", "UNTAGGED"])
def test_editor_persists_and_validates_tag_scope(admin_client, signal):
    tag = Tag.objects.create(name="Find me")
    for scope in (tag.pk, "*"):
        response = post(admin_client, "save/", webhook_input(name=f"{signal} {scope}", signal=signal, tag_id=scope))
        assert response.status_code == 200, response.content
        saved = response.json()["hook"]
        assert saved["tag_id"] == scope
        rule = OutboundWebhook.objects.get(pk=saved["id"])
        assert rule.relationship == str(scope)
    for scope in (None, tag.pk + 10_000, "Find me", True):
        assert post(admin_client, "save/", webhook_input(signal=signal, tag_id=scope)).status_code == 400
    assert post(admin_client, "save/", webhook_input(tag_id=tag.pk)).status_code == 400
    assert post(admin_client, "save/", webhook_input(signal=signal, tag_id=tag.pk, folder_id="*")).status_code == 400
    assert post(admin_client, "save/", webhook_input(signal=signal, tag_id=tag.pk, ref="archivebox.core.models.Tag")).status_code == 400


def test_membership_rule_pickers_in_browser(live_server, browser_runtime, admin_user):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])

    tag = Tag.objects.create(name="Architecture research")
    parent = Folder.objects.create(name="Library")
    folder = Folder.objects.create(name="Reading", parent=parent)
    admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{admin_url}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        page.goto(f"{admin_url}/admin/rules/")
        page.get_by_role("button", name="New rule", exact=True).click()

        for event in ("Tagged", "Untagged", "Added to folder", "Removed from folder"):
            expect(page.get_by_role("radio", name=event, exact=True)).to_be_visible()
        expect(page.get_by_role("radio", name="Relationship added", exact=True)).to_have_count(0)
        expect(page.get_by_role("radio", name="Relationships cleared", exact=True)).to_have_count(0)

        for event, query, choice in (
            ("Tagged", "architecture", tag.name),
            ("Added to folder", "reading", f"{parent.name} / {folder.name}"),
        ):
            page.get_by_role("radio", name=event, exact=True).check()
            page.locator("#scope-field").get_by_role("combobox").click()
            suggestions = page.get_by_role("searchbox", name="Search", exact=True)
            suggestions.fill(query)
            page.get_by_role("option", name=choice, exact=True).click()
            expect(page.locator("#scope-field").get_by_role("combobox")).to_contain_text(choice)
            page.get_by_role("textbox", name="Name", exact=True).fill(f"{event} rule")
            page.locator("#add-action").select_option("add_tags")
            page.locator("#actions input[type=text]").first.fill("Filed")
            page.get_by_role("button", name="Save rule", exact=True).click()
            expect(page.locator("#toast")).to_have_text("Rule saved")
            page.reload()
            expect(page.locator("#scope-field").get_by_role("combobox")).to_contain_text(choice)
            page.get_by_role("button", name="Close editor", exact=True).click()
            page.get_by_role("button", name="New rule", exact=True).click()
        browser.close()

    tagged = OutboundWebhook.objects.get(name="Tagged rule")
    assert tagged.signal == "TAGGED"
    assert tagged.relationship == str(tag.pk) and tagged.folder_id is None
    filed = OutboundWebhook.objects.get(name="Added to folder rule")
    assert filed.signal == "FOLDER_ENTERED"
    assert filed.folder_id == folder.pk and filed.relationship == ""
