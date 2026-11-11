"""Enrichment UI and failure paths using real database rows and saved files."""

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_automation_rules import snapshot

pytestmark = pytest.mark.django_db


def test_ai_defaults_disabled_and_validates_model(admin_client):
    from archivebox.automation.ai_models import AISettings

    response = admin_client.get("/admin/automation/ai/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert not AISettings.objects.get().enabled
    response = admin_client.post(
        "/admin/automation/ai/",
        {"model": "missing-provider", "apply_tags": "on", "language": "English", "tag_style": "as_generated"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert b"provider/model" in response.content
    assert AISettings.objects.get().model == ""


def test_no_capture_content_is_visible_failure_not_fabricated_summary(admin_user):
    from archivebox.automation.ai import enqueue, run_pending_enrichment
    from archivebox.automation.ai_models import AISettings, Enrichment

    item = snapshot(admin_user)
    item.notes = "My human note"
    item.save(update_fields=["notes"])
    settings = AISettings.objects.create()
    job = enqueue(item, settings)
    assert run_pending_enrichment()
    job.refresh_from_db()
    item.refresh_from_db()
    assert job.status == Enrichment.Status.FAILED
    assert "No saved text or HTML" in job.error
    assert job.summary == "" and job.tags == []
    assert item.notes == "My human note" and item.tags.count() == 0


def test_ai_rejects_unvalidated_output_without_modifying_tags(admin_user):
    from archivebox.automation.ai import finish
    from archivebox.automation.ai_models import Enrichment

    item = snapshot(admin_user)
    job = Enrichment.objects.create(snapshot=item, status="running")
    with pytest.raises(ValueError, match="invalid summary object"):
        finish(job, {"summary": "pretend result", "tags": [], "unexpected": True})
    job.refresh_from_db()
    assert job.summary == "" and item.tags.count() == 0


def test_real_opencode_analysis_session_is_tool_denied(live_opencode):
    import requests
    from abx_plugins.plugins.opencode import analysis, runtime

    settings = live_opencode.settings
    session_id = analysis.create_session(
        settings["config"],
        data_dir=settings["archivebox_data_dir"],
        title="ArchiveBox analysis permission verification",
    )
    response = requests.get(
        f"{settings['origin']}/session/{session_id}",
        params={"directory": str(settings["workdir"])},
        auth=runtime._server_auth(settings),
        timeout=15,
    )
    response.raise_for_status()
    assert response.json()["permission"] == [{"permission": "*", "pattern": "*", "action": "deny"}]
    assert analysis.result(settings["config"], data_dir=settings["archivebox_data_dir"], session_id=session_id) is None


def test_ai_history_filter_scopes_gallery_to_selected_jobs(admin_client, admin_user):
    from archivebox.automation.ai import enqueue
    from archivebox.automation.ai_models import AISettings

    settings = AISettings.objects.create()
    selected = snapshot(admin_user, "https://news.ycombinator.com/item?id=2")
    other = snapshot(admin_user, "https://news.ycombinator.com/item?id=3")
    enqueue(selected, settings)
    enqueue(other, settings)
    response = admin_client.get("/admin/automation/ai/", {"snapshot": str(selected.pk)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [job.snapshot_id for job in response.context["jobs"]] == [selected.pk]


def test_ai_preferences_save_preview_and_freeze_at_queue_time(admin_client, admin_user):
    from archivebox.automation.ai import enqueue, format_tags
    from archivebox.automation.ai_models import AISettings

    response = admin_client.post(
        "/admin/automation/ai/",
        {
            "model": "openai/gpt-5.4-mini",
            "language": "French",
            "tag_style": "lower_hyphens",
            "allowed_tags": "Home Automation\nHardware\nHome Automation",
            "instructions": "Be concise.",
            "apply_tags": "on",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    settings = AISettings.objects.get()
    assert settings.allowed_tags == "Home Automation\nHardware"
    page = admin_client.get("/admin/automation/ai/", HTTP_HOST=ADMIN_TEST_HOST)
    assert b"Write the summary and topics in French" in page.content
    assert b"Prompt preview" in page.content
    job = enqueue(snapshot(admin_user), settings)
    settings.language = "English"
    settings.save()
    assert job.preferences["language"] == "French"
    assert format_tags(["hardware", "Unapproved"], job.preferences) == ["Hardware"]
    assert format_tags(["Machine Learning"], {"tag_style": "lower_hyphens"}) == ["machine-learning"]
