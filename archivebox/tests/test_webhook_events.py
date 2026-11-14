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
        emit_event(snapshot, "BEFORE_CAPTURE")
    assert records(hook).last().exit_code == 4
    assert not snapshot.archiveresult_set.exists()


def test_event_catalog_uses_model_icons_and_only_valid_membership_arguments():
    from signal_webhooks.utils import model_from_reference

    for item in event_catalog():
        assert item["emoji"] == model_from_reference(item["ref"]).emoji
        membership = any(event.get("membership") for event in item["events"])
        assert membership == (item["ref"] == "archivebox.core.models.Snapshot")
