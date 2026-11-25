"""Rules use the shared model, and old URLs lead to the single editor."""

import json

import pytest
from django.urls import reverse

from archivebox.api.models import OutboundWebhook
from archivebox.core.admin_site import archivebox_admin

pytestmark = pytest.mark.django_db
HOST = "admin.archivebox.localhost:5797"


def test_rules_canonical_page_and_native_model_labels(admin_client):
    assert reverse("webhooks:index") == "/admin/rules/"
    response = admin_client.get("/admin/rules/", HTTP_HOST=HOST)
    assert response.status_code == 200
    body = response.content.decode()
    for label in ("<h1>Rules</h1>", "New rule", "Save rule", "Rule editor", 'href="/admin/rules/"'):
        assert label in body
    assert "New webhook" not in body
    assert OutboundWebhook._meta.verbose_name == "Rule"
    assert OutboundWebhook._meta.verbose_name_plural == "Rules"
    assert OutboundWebhook._meta.db_table == "api_outboundwebhook"
    assert not archivebox_admin.is_registered(OutboundWebhook)
    native = admin_client.get("/admin/api/outboundwebhook/add/", HTTP_HOST=HOST)
    assert native.status_code == 302
    assert native["Location"] == "/admin/rules/?webhook=new"


def test_old_model_admin_opens_the_same_rule_without_accepting_writes(admin_client, admin_user):
    rule = OutboundWebhook.objects.create(
        name="Existing HTTP rule",
        ref="archivebox.core.models.Snapshot",
        signal="CREATE",
        endpoint="https://archivebox.io/",
        created_by=admin_user,
        enabled=False,
    )
    index = admin_client.get("/admin/api/outboundwebhook/", HTTP_HOST=HOST)
    assert index.status_code == 302
    assert index["Location"] == "/admin/rules/"
    for suffix in ("change/", "delete/", "history/"):
        url = f"/admin/api/outboundwebhook/{rule.pk}/{suffix}"
        response = admin_client.get(url, HTTP_HOST=HOST)
        assert response.status_code == 302
        assert response["Location"] == f"/admin/rules/?webhook={rule.pk}"
        assert admin_client.post(url, {"name": "Changed elsewhere"}, HTTP_HOST=HOST).status_code == 405
    rule.refresh_from_db()
    assert rule.name == "Existing HTTP rule"


@pytest.mark.parametrize(
    "suffix",
    ["", "data/", "save/", "preview/", "06a1d8644fe675c68000f2324c763839/delete/", "future/path/", "future/a%3Fb/"],
)
@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_legacy_rules_redirect_preserves_suffix_query_and_method(admin_client, suffix, method):
    response = getattr(admin_client, method)("/admin/webhooks/" + suffix + "?folder=x%2Fy&view=activity", HTTP_HOST=HOST)
    assert response.status_code == 307
    assert response["Location"] == "/admin/rules/" + suffix + "?folder=x%2Fy&view=activity"


def test_legacy_post_follows_to_real_rules_save_without_losing_body(admin_client):
    payload = {
        "name": "Legacy rule",
        "ref": "archivebox.core.models.Snapshot",
        "signal": "BEFORE_CAPTURE",
        "enabled": False,
        "actions": [{"type": "add_tags", "add_tags": "Reviewed"}],
    }
    response = admin_client.post("/admin/webhooks/save/", json.dumps(payload), content_type="application/json", HTTP_HOST=HOST, follow=True)
    assert response.status_code == 200
    assert response.redirect_chain == [("/admin/rules/save/", 307)]
    rule = OutboundWebhook.objects.get(name="Legacy rule")
    assert rule.actions == payload["actions"]
    assert not rule.enabled


@pytest.mark.django_db(transaction=True)
def test_rule_display_migration_emits_no_schema_sql():
    from importlib import import_module

    from django.apps import apps
    from django.db import connection
    from django.db.migrations.state import ProjectState

    migration = import_module("archivebox.api.migrations.0005_rule_display_names").Migration
    before = ProjectState.from_apps(apps)
    after = before.clone()
    operation = migration.operations[0]
    operation.state_forwards("api", after)
    with connection.schema_editor(collect_sql=True, atomic=False) as editor:
        operation.database_forwards("api", editor, before, after)
    assert editor.collected_sql == []
    assert after.apps.get_model("api", "OutboundWebhook")._meta.db_table == "api_outboundwebhook"
