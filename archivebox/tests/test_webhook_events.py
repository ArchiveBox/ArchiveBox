import json

import pytest
from django.db import transaction

from archivebox.api.models import OutboundWebhook
from archivebox.api.webhook_events import emit_event, event_catalog
from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process

pytestmark = pytest.mark.django_db(transaction=True)


def subscription(name, signal, actions, **kwargs):
    hook = OutboundWebhook(name=name, ref="archivebox.core.models.Snapshot", signal=signal, actions=actions, **kwargs)
    hook.full_clean()
    hook.save()
    return hook


def records(hook):
    return Process.objects.filter(worker_type="webhook", env__ARCHIVEBOX_WEBHOOK_ID=str(hook.pk)).order_by("created_at", "pk")


def test_create_delete_payload_and_transaction_commit():
    actions = [{"type": "python", "code": "import sys; print(sys.stdin.read())"}]
    created = subscription("creation", "CREATE", actions)
    deleted = subscription("deletion", "DELETE", actions)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/")
    with transaction.atomic():
        snapshot = Snapshot.objects.create(crawl=crawl, url="https://news.ycombinator.com/")
        assert not records(created).exists()
    output = json.loads(records(created).get().stdout)
    assert output["id"] == str(snapshot.pk)
    assert output["url"] == snapshot.url
    assert output["object_type"] == "core.Snapshot"
    assert output["event"] == "CREATE"

    pk = str(snapshot.pk)
    # The real deletion path removes files outside the collector's DB transaction;
    # its post_delete callback must preserve identity after that collector commits.
    Snapshot.objects.only("id").get(pk=pk).delete()
    output = json.loads(records(deleted).get().stdout)
    assert output["id"] == pk
    assert output["url"] == "https://news.ycombinator.com/"
    assert output["event"] == "DELETE"


def test_snapshot_create_payload_includes_initial_crawl_tags():
    hook = subscription("creation with tags", "CREATE", [{"type": "python", "code": "import sys; print(sys.stdin.read())"}])
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", tags_str="News, Research")
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://news.ycombinator.com/")
    payload = json.loads(records(hook).get().stdout)
    assert payload["tags"] == sorted(snapshot.tags.values_list("name", flat=True)) == ["News", "Research"]


def test_snapshot_update_input_freezes_tags_before_commit():
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", tags_str="News")
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://news.ycombinator.com/")
    hook = subscription("updated tags", "UPDATE", [{"type": "python", "code": "import sys; print(sys.stdin.read())"}])
    with transaction.atomic():
        snapshot.title = "Changed title"
        snapshot.save(update_fields=["title"])
        snapshot.save_tags(["Later"])
    payload = json.loads(records(hook).get().stdout)
    assert payload["tags"] == ["News"]
    assert list(snapshot.tags.values_list("name", flat=True)) == ["Later"]


def test_result_failure_projection_emits_completion_once():
    from archivebox.core.models import ArchiveResult
    from archivebox.services.snapshot_service import finalize_completed_snapshot

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/")
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://news.ycombinator.com/", status="started")
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="wget", hook_name="on_Snapshot__wget", status="started")
    hook = OutboundWebhook(
        name="result completion",
        ref="archivebox.core.models.ArchiveResult",
        signal="CAPTURE_COMPLETED",
        actions=[{"type": "python", "code": "import sys; print(sys.stdin.read())"}],
    )
    hook.full_clean()
    hook.save()
    finalize_completed_snapshot(str(snapshot.pk), owned_retry_at=snapshot.retry_at, was_sealed=False, error="Capture worker exited")
    result.refresh_from_db()
    assert result.status == "failed" and result.end_ts
    payload = json.loads(records(hook).get().stdout)
    assert payload["id"] == str(result.pk) and payload["status"] == "failed"
    assert payload["notes"] == "Capture worker exited"
    ArchiveResult.objects.filter(pk=result.pk).update(status="failed")
    assert records(hook).count() == 1


def test_rollback_and_action_writes_do_not_dispatch_more_sequences():
    hook = subscription("tag created", "CREATE", [{"type": "add_tags", "add_tags": "news"}])
    updated = subscription("observe updates", "UPDATE", [{"type": "python", "code": "print('updated')"}])
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/")
    with pytest.raises(ValueError), transaction.atomic():
        Snapshot.objects.create(crawl=crawl, url="https://news.ycombinator.com/rollback")
        raise ValueError("rollback")
    assert not records(hook).exists()
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://news.ycombinator.com/")
    assert list(snapshot.tags.values_list("name", flat=True)) == ["news"]
    assert records(hook).count() == 1
    assert not records(updated).exists()


def test_explicit_m2m_signal_and_stop_processing():
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/")
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://news.ycombinator.com/")
    hook = subscription("first", "M2M_ADD", [{"type": "python", "code": "print('first')"}], stop_processing=True)
    later = subscription("later", "M2M_ADD", [{"type": "python", "code": "print('later')"}])
    tag = Tag.objects.create(name="top stories")
    snapshot.tags.add(tag)
    assert records(hook).get().stdout.strip() == "first"
    assert not records(later).exists()


def test_blocking_preparation_changes_native_config_and_failure_stops_capture():
    from abx_plugins.plugins.base.django import webhook_event

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/")
    snapshot = Snapshot.objects.create(crawl=crawl, url="https://news.ycombinator.com/")
    hook = subscription("prepare", "BEFORE_CAPTURE", [{"type": "config_overrides", "config_overrides": {"YTDLP_MAX_SIZE": "1256m"}}])
    emit_event(snapshot, "BEFORE_CAPTURE")
    snapshot.refresh_from_db()
    assert snapshot.config["YTDLP_MAX_SIZE"] == "1256m"
    assert records(hook).get().exit_code == 0
    hook.actions = [{"type": "shell", "command": "printf 'preparation failed' >&2; exit 4"}]
    hook.save()
    with pytest.raises(RuntimeError, match="BEFORE_CAPTURE webhook failed"):
        webhook_event.send(sender=Snapshot, instance=snapshot, event="BEFORE_CAPTURE")
    assert records(hook).last().exit_code == 4
    assert not snapshot.archiveresult_set.exists()


def test_event_catalog_uses_model_icons_and_only_valid_membership_arguments():
    from signal_webhooks.utils import model_from_reference

    for item in event_catalog():
        assert item["emoji"] == model_from_reference(item["ref"]).emoji
        membership = any(event.get("membership") for event in item["events"])
        assert membership == (item["ref"] == "archivebox.core.models.Snapshot")


def test_late_native_model_registration_exposes_and_delivers_events(admin_client):
    from django.contrib.auth.models import Group
    from django.core.exceptions import ValidationError
    from signal_webhooks.settings import webhook_settings
    from signal_webhooks.utils import reference_for_model
    from abx_plugins.plugins.base.django import register_webhooks, webhook_event
    from archivebox.tests.test_webhook_views import BASE, HOST, post, webhook_input

    ref = reference_for_model(Group)
    assert ref not in webhook_settings.HOOKS
    register_webhooks(Group, events={"CREATE": {"label": "Group created"}, "REVIEWED": {}})
    try:
        register_webhooks(Group)
        assert Group.webhook_events == {"CREATE": {"label": "Group created"}, "REVIEWED": {}}
        response = admin_client.get(BASE + "data/", HTTP_HOST=HOST)
        assert response.status_code == 200
        data = response.json()
        entry = next(item for item in data["models"] if item["ref"] == ref)
        assert entry["emoji"]
        assert [event["label"] for event in entry["events"] if event["key"] == "CREATE"] == ["Group created"]
        assert next(event for event in entry["events"] if event["key"] == "REVIEWED")["label"] == "Reviewed"
        assert data["signal_labels"]["REVIEWED"] == "Reviewed"

        hooks = {}
        for event in ("CREATE", "REVIEWED"):
            response = post(
                admin_client,
                "save/",
                webhook_input(
                    name=f"Group {event}",
                    ref=ref,
                    signal=event,
                    enabled=True,
                    actions=[{"type": "python", "code": "import sys; print(sys.stdin.read())"}],
                ),
            )
            assert response.status_code == 200, response.content
            hooks[event] = OutboundWebhook.objects.get(name=f"Group {event}")
            hooks[event].full_clean()

        group = Group.objects.create(name="Reviewed captures")
        process = records(hooks["CREATE"]).get()
        assert process.exit_code == 0
        created = json.loads(process.stdout)
        assert created["id"] == str(group.pk) and created["name"] == group.name
        assert created["object_type"] == "auth.Group" and created["event"] == "CREATE"
        with transaction.atomic():
            webhook_event.send(sender=Group, instance=group, event="REVIEWED", reason="manual")
            assert not records(hooks["REVIEWED"]).exists()
        process = records(hooks["REVIEWED"]).get()
        assert process.exit_code == 0
        reviewed = json.loads(process.stdout)
        assert reviewed["id"] == str(group.pk) and reviewed["name"] == group.name
        assert reviewed["object_type"] == "auth.Group" and reviewed["event"] == "REVIEWED"
        assert reviewed["reason"] == "manual"

        invalid = OutboundWebhook(
            name="Unsupported review",
            ref=reference_for_model(Tag),
            signal="REVIEWED",
            endpoint="https://example.com/",
        )
        with pytest.raises(ValidationError, match="Choose an event for this object type"):
            invalid.full_clean()

        webhook_settings.HOOKS[ref] = None
        register_webhooks(Group)
        assert webhook_settings.HOOKS[ref] is None
        assert all(item["ref"] != ref for item in event_catalog())
        Group.objects.create(name="Unsubscribed captures")
        assert records(hooks["CREATE"]).count() == 1
        webhook_event.send(sender=Group, instance=group, event="REVIEWED")
        assert records(hooks["REVIEWED"]).count() == 1
    finally:
        OutboundWebhook.objects.filter(ref=ref).delete()
        webhook_settings.HOOKS.pop(ref)
        del Group.webhook_events


def test_registered_process_status_events_follow_real_subprocess(tmp_path):
    import sys
    from abx_plugins.plugins.base.django import register_webhooks
    from archivebox.machine.models import Machine, NetworkInterface

    # Initialize the runner before subscribing so its own startup is not an event
    # belonging to the child process under test.
    Process.current()
    declarations = Process.webhook_events
    transitions = Process.webhook_status_events
    register_webhooks(Process)
    assert Process.webhook_events is declarations
    assert Process.webhook_status_events is transitions
    hooks = {}
    for event in ("STARTED", "EXITED"):
        hook = OutboundWebhook(
            name=f"Process {event}",
            ref="archivebox.machine.models.Process",
            signal=event,
            actions=[{"type": "python", "code": "import sys; print(sys.stdin.read())"}],
        )
        hook.full_clean()
        hook.save()
        hooks[event] = hook
    process = Process.objects.create(
        machine=Machine.current(),
        iface=NetworkInterface.current(),
        cmd=[sys.executable, "-c", "print('child completed')"],
        pwd=str(tmp_path),
    )
    process.launch()
    assert process.status == "exited" and process.exit_code == 0
    assert process.stdout.strip() == "child completed"
    for event, status in (("STARTED", "running"), ("EXITED", "exited")):
        action = records(hooks[event]).get()
        assert action.exit_code == 0
        payload = json.loads(action.stdout)
        assert payload["id"] == str(process.pk)
        assert payload["event"] == event and payload["status"] == status
