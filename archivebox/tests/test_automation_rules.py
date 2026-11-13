"""Rules use real HTTP forms, database snapshots and an explicit audit trail."""

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def rule_data(**overrides):
    return {
        "name": "Hacker News",
        "enabled": "on",
        "position": 0,
        "trigger": "capture",
        "match": "all",
        "add_tags": "Hacker News, reading",
        "conditions-TOTAL_FORMS": "1",
        "conditions-INITIAL_FORMS": "0",
        "conditions-MIN_NUM_FORMS": "0",
        "conditions-MAX_NUM_FORMS": "20",
        "conditions-0-field": "domain",
        "conditions-0-operator": "equals",
        "conditions-0-value": "news.ycombinator.com",
        **overrides,
    }


def snapshot(user, url="https://news.ycombinator.com/item?id=1"):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls=url, created_by=user)
    return Snapshot.objects.create(url=url, crawl=crawl, status=Snapshot.StatusChoices.SEALED)


def test_rule_preview_then_apply_records_real_changes(admin_client, admin_user):
    from archivebox.automation.models import Rule, RuleRun

    item = snapshot(admin_user)
    excluded = snapshot(admin_user, "https://news.ycombinator.com.evil.example/item?id=1")
    response = admin_client.post("/admin/automation/new/", rule_data(), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    rule = Rule.objects.get(name="Hacker News")
    response = admin_client.get(response["Location"], HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [obj.pk for obj in response.context["snapshots"]] == [item.pk]
    assert item.tags.count() == 0
    assert RuleRun.objects.count() == 0
    response = admin_client.post(
        f"/admin/automation/{rule.pk}/preview/",
        {"preview": response.context["preview_token"]},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    assert set(item.tags.values_list("name", flat=True)) == {"Hacker News", "reading"}
    assert excluded.tags.count() == 0
    run = RuleRun.objects.get(snapshot=item)
    assert run.matched and not run.automatic
    assert run.changes == {"added_tags": ["Hacker News", "reading"]}


def test_automatic_rules_apply_once_to_future_completed_snapshots(admin_client, admin_user):
    from archivebox.automation.models import RuleRun
    from archivebox.automation.service import run_pending_rules

    older = snapshot(admin_user)
    assert admin_client.post("/admin/automation/new/", rule_data(), HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    newer = snapshot(admin_user)
    assert run_pending_rules() == 1
    assert set(newer.tags.values_list("name", flat=True)) == {"Hacker News", "reading"}
    assert older.tags.count() == 0
    assert run_pending_rules() == 0
    assert RuleRun.objects.count() == 1


def test_rule_preview_invalidated_after_edit(admin_client, admin_user):
    from archivebox.automation.models import Rule

    item = snapshot(admin_user)
    admin_client.post("/admin/automation/new/", rule_data(), HTTP_HOST=ADMIN_TEST_HOST)
    rule = Rule.objects.get()
    response = admin_client.get(f"/admin/automation/{rule.pk}/preview/", HTTP_HOST=ADMIN_TEST_HOST)
    token = response.context["preview_token"]
    rule.permissions = "public"
    rule.save()
    response = admin_client.post(f"/admin/automation/{rule.pk}/preview/", {"preview": token}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"rule changed" in response.content
    assert item.tags.count() == 0


def test_rule_validation_requires_condition_and_action(admin_client):
    from archivebox.automation.models import Rule

    response = admin_client.post("/admin/automation/new/", rule_data(add_tags=""), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"Choose at least one action" in response.content
    assert not Rule.objects.exists()
    data = rule_data()
    data["conditions-0-value"] = ""
    response = admin_client.post("/admin/automation/new/", data, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert not Rule.objects.exists()


def test_rules_require_superuser(client):
    response = client.get("/admin/automation/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302 and "/login/" in response["Location"]


def test_automatic_rule_order_and_stop_preserve_later_actions(admin_client, admin_user):
    from archivebox.automation.models import Rule, RuleCondition, RuleRun
    from archivebox.automation.service import run_pending_rules
    from archivebox.core.models import Folder

    folder = Folder.objects.create(name="News")
    first = Rule.objects.create(name="First", created_by=admin_user, position=1, add_tags="first", folder=folder, stop_processing=True)
    second = Rule.objects.create(name="Second", created_by=admin_user, position=2, add_tags="second")
    for rule in (first, second):
        RuleCondition.objects.create(rule=rule, field="domain", operator="equals", value="news.ycombinator.com")
    item = snapshot(admin_user)
    run_pending_rules()
    item.refresh_from_db()
    assert item.folder_id == folder.pk
    assert list(item.tags.values_list("name", flat=True)) == ["first"]
    assert RuleRun.objects.get(rule=second).changes["skipped"]
    assert run_pending_rules() == 0


def test_manual_run_for_one_rule_does_not_hide_automatic_rule(admin_user):
    from archivebox.automation.models import Rule, RuleCondition, RuleRun
    from archivebox.automation.service import apply_rule, run_pending_rules

    first = Rule.objects.create(name="First", created_by=admin_user, add_tags="first")
    second = Rule.objects.create(name="Second", created_by=admin_user, add_tags="second")
    for rule in (first, second):
        RuleCondition.objects.create(rule=rule, field="domain", operator="equals", value="news.ycombinator.com")
    item = snapshot(admin_user)
    apply_rule(first, item, automatic=True)
    apply_rule(second, item, automatic=False)
    assert run_pending_rules() == 1
    assert RuleRun.objects.filter(rule=second, automatic=True).exists()


def test_nested_groups_and_negative_contains_via_rule_form(admin_client, admin_user):
    import json
    from archivebox.automation.models import Rule
    from archivebox.automation.service import matches

    data = rule_data(
        **{
            "condition-groups": json.dumps({"g1": {"parent": "", "match": "any"}, "g2": {"parent": "g1", "match": "all"}}),
            "conditions-TOTAL_FORMS": "4",
            "conditions-1-group": "g1",
            "conditions-1-field": "title",
            "conditions-1-operator": "contains",
            "conditions-1-value": "hardware",
            "conditions-2-group": "g2",
            "conditions-2-field": "url",
            "conditions-2-operator": "not_contains",
            "conditions-2-value": "private",
            "conditions-3-group": "g2",
            "conditions-3-field": "title",
            "conditions-3-operator": "contains",
            "conditions-3-value": "news",
        },
    )
    response = admin_client.post("/admin/automation/new/", data, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    rule = Rule.objects.get()
    item = snapshot(admin_user)
    item.title = "Daily news"
    item.save()
    assert matches(rule, item)
    item.url = "https://news.ycombinator.com/private"
    assert not matches(rule, item)
    item.title = "New hardware"
    assert matches(rule, item)
    item.url = "https://example.com/"
    assert not matches(rule, item)
    data["condition-groups"] = json.dumps({"g1": {"parent": "g2", "match": "all"}, "g2": {"parent": "g1", "match": "any"}})
    response = admin_client.post("/admin/automation/new/", data, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200 and b"must form a tree" in response.content


@pytest.mark.django_db(transaction=True)
def test_real_tag_and_folder_events_are_durable_and_non_recursive(admin_user):
    from archivebox.automation.models import Rule, RuleCondition, RuleEvent, RuleRun
    from archivebox.automation.service import run_pending_rules
    from archivebox.core.models import Tag, Folder

    item = snapshot(admin_user)
    added = Rule.objects.create(
        name="After adding reading",
        created_by=admin_user,
        trigger="tag_added",
        add_tags="organized",
        remove_tags="reading",
    )
    removed = Rule.objects.create(name="After removing reading", created_by=admin_user, trigger="tag_removed", add_tags="removed")
    folder_rule = Rule.objects.create(name="Moved", created_by=admin_user, trigger="folder_moved", add_tags="filed")
    for rule in [added, removed]:
        RuleCondition.objects.create(rule=rule, field="event_tag", operator="equals", value="reading")
    RuleCondition.objects.create(rule=folder_rule, field="domain", operator="equals", value="news.ycombinator.com")
    tag, _ = Tag.get_or_create_by_name("reading")
    item.add_tag_ids([tag.pk])
    item.add_tag_ids([tag.pk])
    assert RuleEvent.objects.filter(kind="tag_added").count() == 1
    assert run_pending_rules() == 1
    assert list(item.tags.values_list("name", flat=True)) == ["organized"]
    assert RuleEvent.objects.count() == 1
    assert run_pending_rules() == 0
    item.add_tag_ids([tag.pk])
    item.remove_tag_ids([tag.pk])
    item.remove_tag_ids([tag.pk])
    assert run_pending_rules() == 2
    assert item.tags.filter(name="removed").exists()
    folder = Folder.objects.create(name="Reading")
    item.folder = folder
    item.save(update_fields=["folder"])
    assert run_pending_rules() == 1
    assert item.tags.filter(name="filed").exists()
    assert RuleRun.objects.filter(rule=folder_rule, event__kind="folder_moved").count() == 1
    assert run_pending_rules() == 0


@pytest.mark.django_db(transaction=True)
def test_tag_event_waits_for_capture_completion(admin_user):
    from archivebox.automation.models import Rule, RuleCondition, RuleEvent
    from archivebox.automation.service import run_pending_rules
    from archivebox.core.models import Snapshot, Tag

    rule = Rule.objects.create(name="After capture", created_by=admin_user, trigger="tag_added", add_tags="finished")
    RuleCondition.objects.create(rule=rule, field="event_tag", operator="equals", value="read")
    item = snapshot(admin_user)
    item.status = Snapshot.StatusChoices.STARTED
    item.save(update_fields=["status"])
    tag, _ = Tag.get_or_create_by_name("read")
    item.add_tag_ids([tag.pk])
    assert RuleEvent.objects.filter(processed_at__isnull=True).count() == 1
    assert run_pending_rules() == 0
    assert not item.tags.filter(name="finished").exists()
    item.status = Snapshot.StatusChoices.SEALED
    item.save(update_fields=["status"])
    assert run_pending_rules() == 1
    assert item.tags.filter(name="finished").exists()


def test_unrelated_snapshot_save_does_not_read_folder_or_reuse_tracking(admin_user):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.automation.models import Rule, RuleCondition, RuleEvent
    from archivebox.core.models import Folder

    rule = Rule.objects.create(name="Folder changes", created_by=admin_user, trigger="folder_moved", add_tags="filed")
    RuleCondition.objects.create(rule=rule, field="domain", operator="equals", value="news.ycombinator.com")
    item = snapshot(admin_user)
    item.folder = Folder.objects.create(name="News")
    item.save(update_fields=["folder"])
    assert RuleEvent.objects.filter(kind="folder_moved").count() == 1
    with CaptureQueriesContext(connection) as queries:
        item.title = "Updated HN title"
        item.save(update_fields=["title"])
    assert not any('SELECT "core_snapshot"."folder_id"' in query["sql"] for query in queries)
    assert RuleEvent.objects.filter(kind="folder_moved").count() == 1


def test_before_crawl_rules_freeze_schema_config_and_depth(admin_client, admin_user):
    import json
    from archivebox.crawls.models import Crawl
    from archivebox.automation.models import RuleRun

    data = rule_data(
        trigger="before_crawl",
        add_tags="",
        config_overrides=json.dumps({"TIMEOUT": 41, "YTDLP_MAX_SIZE": "1256m"}),
        max_depth=1,
    )
    data.update({"conditions-0-field": "crawl_tag", "conditions-0-value": "depth=1"})
    response = admin_client.post("/admin/automation/new/", data, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302, response.content
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", tags_str="depth=1", max_depth=3, created_by=admin_user)
    assert crawl.max_depth == 1
    assert crawl.config["TIMEOUT"] == 41
    assert crawl.config["YTDLP_MAX_SIZE"] == "1256m"
    assert RuleRun.objects.get(crawl=crawl).matched
    crawl.max_depth = 2
    crawl.save()
    assert crawl.max_depth == 2
    assert RuleRun.objects.filter(crawl=crawl).count() == 1


def test_before_snapshot_domain_list_and_plugin_actions_are_once_only(admin_client, admin_user):
    import json
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.automation.capture import prepare_snapshot_rules
    from archivebox.automation.models import Rule, RuleRun

    data = rule_data(trigger="before_snapshot", add_tags="", config_overrides=json.dumps({"TIMEOUT": 29}), disable_plugins=["pdf"])
    data.update(
        {
            "conditions-0-operator": "in",
            "conditions-0-value": "news.ycombinator.com, example.com",
            "conditions-TOTAL_FORMS": "2",
            "conditions-1-field": "url",
            "conditions-1-operator": "contains",
            "conditions-1-value": "item?id=",
        },
    )
    response = admin_client.post("/admin/automation/new/", data, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302, response.content
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/item?id=1", config={"PLUGINS": "title,pdf"}, created_by=admin_user)
    item = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    prepare_snapshot_rules(item)
    assert item.config["TIMEOUT"] == 29
    assert "pdf" not in item.config["PLUGINS"].split(",")
    assert item.config["PLUGINS"] == "title"
    Rule.objects.update(config_overrides={"TIMEOUT": 90})
    prepare_snapshot_rules(item)
    item.refresh_from_db()
    assert item.config["TIMEOUT"] == 29
    assert RuleRun.objects.filter(snapshot=item).count() == 1
    completed = snapshot(admin_user)
    prepare_snapshot_rules(completed)
    assert not RuleRun.objects.filter(snapshot=completed).exists()


@pytest.mark.parametrize("config", [{"DATABASE_NAME": "/tmp/other"}, {"TIMEOUT": "not-a-number"}, {"UNKNOWN_SETTING": True}])
def test_capture_rule_rejects_invalid_configuration(admin_client, config):
    import json
    from archivebox.automation.models import Rule

    response = admin_client.post(
        "/admin/automation/new/",
        rule_data(trigger="before_snapshot", add_tags="", config_overrides=json.dumps(config)),
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert response.context["form"].errors.get("config_overrides")
    assert not Rule.objects.exists()


def test_capture_preview_is_read_only_and_shows_ordered_effective_settings(admin_client, admin_user):
    import json
    from archivebox.automation.models import Rule, RuleRun, RuleEvent
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot

    for priority, timeout, stop in [(1, 19, False), (2, 23, True), (3, 45, False)]:
        response = admin_client.post(
            "/admin/automation/new/",
            rule_data(
                name=f"Priority {priority}",
                position=priority,
                trigger="before_snapshot",
                add_tags="",
                config_overrides=json.dumps({"TIMEOUT": timeout}),
                stop_processing="on" if stop else "",
            ),
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 302
    rule = Rule.objects.get(position=1)
    counts = (Crawl.objects.count(), Snapshot.objects.count(), RuleRun.objects.count(), RuleEvent.objects.count())
    response = admin_client.get(
        f"/admin/automation/{rule.pk}/preview/",
        {"url": "https://news.ycombinator.com/", "plugins": "title,pdf", "max_depth": 0},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert response.context["preview_ready"]
    assert json.loads(response.context["effective_config"])["TIMEOUT"] == 23
    assert [entry["rule"].position for entry in response.context["evaluations"]] == [1, 2, 3]
    assert "skipped" in response.context["evaluations"][2]["changes"]
    assert counts == (Crawl.objects.count(), Snapshot.objects.count(), RuleRun.objects.count(), RuleEvent.objects.count())
    response = admin_client.post(f"/admin/automation/{rule.pk}/preview/", {}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 403


def test_before_crawl_domain_and_url_match_same_seed(admin_client, admin_user):
    import json
    from archivebox.crawls.models import Crawl

    data = rule_data(
        trigger="before_crawl",
        add_tags="",
        config_overrides=json.dumps({"TIMEOUT": 31}),
        **{
            "conditions-TOTAL_FORMS": "2",
            "conditions-1-field": "url",
            "conditions-1-operator": "contains",
            "conditions-1-value": "/specific",
        },
    )
    assert admin_client.post("/admin/automation/new/", data, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    crawl = Crawl.objects.create(
        urls="https://news.ycombinator.com/\nhttps://example.com/specific",
        config={"TIMEOUT": 22},
        created_by=admin_user,
    )
    assert crawl.config["TIMEOUT"] == 22
    assert not crawl.rule_runs.get().matched


@pytest.mark.django_db(transaction=True)
def test_native_runner_resolves_rule_before_snapshot_preparation(admin_client, admin_user):
    import json
    from asgiref.sync import async_to_sync
    from archivebox.services.runner import CrawlRunner
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    data = rule_data(trigger="before_snapshot", add_tags="", config_overrides=json.dumps({"TIMEOUT": 37}), disable_plugins=["pdf"])
    assert admin_client.post("/admin/automation/new/", data, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", config={"PLUGINS": "title,pdf"}, created_by=admin_user)
    item = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    runner = CrawlRunner(crawl, show_progress=False)
    payload = async_to_sync(runner.load_snapshot_payload)(str(item.pk), prepare=False)
    assert payload["config"]["TIMEOUT"] == 37
    assert "pdf" not in payload["selected_plugins"]
    assert payload["selected_plugins"] == ["title"]
    assert payload["config"]["PDF_ENABLED"] is False
    assert item.rule_runs.get().matched
    assert not item.output_dir.exists()
