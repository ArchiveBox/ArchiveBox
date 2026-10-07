from django.test import TestCase


class TestSignalWebhooksSettings(TestCase):
    def test_task_handler_runs_after_transaction_commit(self):
        from signal_webhooks.settings import webhook_settings

        assert webhook_settings.TASK_HANDLER.__name__ == "transaction_on_commit_task_handler"

    def test_webhook_authentication_token_round_trips_encrypted(self):
        from django.db import connection
        from django.forms import modelform_factory
        from archivebox.api.admin import OutboundWebhookAdminForm
        from archivebox.api.models import OutboundWebhook
        from archivebox.base_models.models import get_or_create_system_user_pk

        token = "Bearer local-webhook-regression-test"
        form_class = modelform_factory(
            OutboundWebhook,
            form=OutboundWebhookAdminForm,
            fields=(
                "name",
                "signal",
                "ref",
                "endpoint",
                "headers",
                "auth_token",
                "enabled",
                "keep_last_response",
                "created_by",
            ),
        )
        form = form_class(
            data={
                "name": "Authenticated capture results",
                "signal": "UPDATE",
                "ref": "archivebox.core.models.Snapshot",
                "endpoint": "http://localhost:5678/webhook/capture-results",
                "headers": "{}",
                "auth_token": token,
                "enabled": True,
                "keep_last_response": True,
                "created_by": get_or_create_system_user_pk(),
            },
        )
        assert form.is_valid(), form.errors
        webhook = form.save()
        with connection.cursor() as cursor:
            cursor.execute("SELECT auth_token FROM api_outboundwebhook WHERE name = %s", [webhook.name])
            encrypted = cursor.fetchone()[0]
        assert token not in encrypted
        loaded = OutboundWebhook.objects.get(pk=webhook.pk)
        assert loaded.auth_token == token
        assert loaded.default_headers()["Authorization"] == token
        edit_form = form_class(instance=loaded, data={**form.data, "auth_token": ""})
        assert token not in str(edit_form["auth_token"])
        assert edit_form.is_valid(), edit_form.errors
        edit_form.save()
        assert OutboundWebhook.objects.get(pk=webhook.pk).auth_token == token

    def test_sealing_snapshot_schedules_one_completion_webhook(self):
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(urls="https://example.com")
        snapshot = Snapshot.objects.create(crawl=crawl, url="https://example.com", status="started")
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            assert snapshot.seal()
            assert snapshot.seal()

        deliveries = [callback for callback in callbacks if callback.__name__ == "run_webhook"]
        assert len(deliveries) == 1
        captured = dict(zip(deliveries[0].__code__.co_freevars, (cell.cell_contents for cell in deliveries[0].__closure__)))
        payload = captured["kwargs"]
        snapshot.refresh_from_db()
        assert payload["method"] == "UPDATE"
        assert payload["data"]["pk"] == str(snapshot.pk)
        assert payload["data"]["fields"]["status"] == snapshot.status == "sealed"
        assert payload["data"]["fields"]["output_size"] == snapshot.output_size
