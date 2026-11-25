"""Rules use the shared model, and old URLs lead to the single editor."""

import json

import pytest
from django.urls import reverse

from archivebox.api.models import Rule
from archivebox.core.admin_site import archivebox_admin

pytestmark = pytest.mark.django_db
HOST = "admin.archivebox.localhost:5797"


def test_rules_canonical_page_and_native_model_labels(admin_client):
    assert reverse("rules:index") == "/admin/rules/"
    response = admin_client.get("/admin/rules/", HTTP_HOST=HOST)
    assert response.status_code == 200
    body = response.content.decode()
    for label in ("<h1>Rules</h1>", "New rule", "Save rule", "Rule editor", "Stop processing other rules", 'href="/admin/rules/"'):
        assert label in body
    assert "New webhook" not in body
    assert Rule._meta.verbose_name == "Rule"
    assert Rule._meta.verbose_name_plural == "Rules"
    assert Rule._meta.db_table == "api_outboundwebhook"
    assert not archivebox_admin.is_registered(Rule)
    native = admin_client.get("/admin/api/outboundwebhook/add/", HTTP_HOST=HOST)
    assert native.status_code == 302
    assert native["Location"] == "/admin/rules/?rule=new"


def test_old_model_admin_opens_the_same_rule_without_accepting_writes(admin_client, admin_user):
    rule = Rule.objects.create(
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
        assert response["Location"] == f"/admin/rules/?rule={rule.pk}"
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
    rule = Rule.objects.get(name="Legacy rule")
    assert rule.actions == payload["actions"]
    assert not rule.enabled


@pytest.mark.django_db(transaction=True)
def test_rule_display_migration_emits_no_schema_sql():
    from importlib import import_module

    from django.db import connection
    from django.db.migrations.loader import MigrationLoader

    migration = import_module("archivebox.api.migrations.0005_rule_display_names").Migration
    before = MigrationLoader(connection).project_state([("api", "0004_retain_webhook_health_counters")])
    after = before.clone()
    operation = migration.operations[0]
    operation.state_forwards("api", after)
    with connection.schema_editor(collect_sql=True, atomic=False) as editor:
        operation.database_forwards("api", editor, before, after)
    assert editor.collected_sql == []
    assert after.apps.get_model("api", "OutboundWebhook")._meta.db_table == "api_outboundwebhook"


@pytest.mark.django_db(transaction=True)
def test_rule_rename_preserves_existing_rule_and_permission(admin_user):
    from io import StringIO

    from django.contrib.auth.models import Permission
    from django.core.management import call_command
    from django.db import connection
    from django.db.migrations.loader import MigrationLoader

    previous = "0006_rule_event_scopes"
    current = "0007_rename_outboundwebhook_rule"
    call_command("migrate", "api", previous, stdout=StringIO())
    try:
        apps = MigrationLoader(connection).project_state([("api", previous)]).apps
        existing_rule = apps.get_model("api", "OutboundWebhook").objects.create(
            name="Existing snapshot rule",
            ref="archivebox.core.models.Snapshot",
            signal="UPDATE",
            endpoint="https://archivebox.io/",
            created_by_id=admin_user.pk,
            enabled=False,
        )
        permission = Permission.objects.get(
            content_type__app_label="api",
            content_type__model="outboundwebhook",
            codename="view_outboundwebhook",
        )
        admin_user.user_permissions.add(permission)
        sql = StringIO()
        call_command("sqlmigrate", "api", current, stdout=sql)
        assert not any(statement in sql.getvalue().upper() for statement in ("ALTER TABLE", "CREATE TABLE", "DROP TABLE"))
    finally:
        call_command("migrate", "api", current, stdout=StringIO())
    rule = Rule.objects.get(pk=existing_rule.pk)
    assert (rule.name, rule.ref, rule.endpoint, rule.created_by_id, rule.enabled) == (
        existing_rule.name,
        existing_rule.ref,
        existing_rule.endpoint,
        admin_user.pk,
        False,
    )
    assert admin_user.rule_set.get() == rule
    permission.refresh_from_db()
    assert permission.codename == "view_rule"
    assert permission.content_type.model == "rule"
    assert admin_user.user_permissions.get(pk=permission.pk) == permission
