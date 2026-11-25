from django.test import TestCase


class TestSignalWebhooksSettings(TestCase):
    def test_task_handler_runs_after_transaction_commit(self):
        from signal_webhooks.settings import webhook_settings

        assert webhook_settings.TASK_HANDLER.__name__ == "transaction_on_commit_task_handler"

    def test_webhook_authentication_token_round_trips_encrypted(self):
        from django.contrib.auth import get_user_model
        from django.db import connection

        from archivebox.api.models import Rule

        token = "Bearer local-webhook-regression-test"
        user = get_user_model().objects.create_superuser(username="rules-admin", password="rules-test-password")
        assert self.client.login(username=user.username, password="rules-test-password")
        host = "admin.archivebox.localhost:5797"
        payload = {
            "name": "Authenticated capture results",
            "signal": "UPDATE",
            "ref": "archivebox.core.models.Snapshot",
            "actions": [{"type": "http_request", "method": "POST", "endpoint": "https://archivebox.io/", "headers": {}}],
            "auth_token": token,
            "enabled": False,
            "keep_last_response": True,
        }
        response = self.client.post("/admin/rules/save/", payload, content_type="application/json", HTTP_HOST=host)
        assert response.status_code == 200, response.content
        assert token.encode() not in response.content
        rule = Rule.objects.get(pk=response.json()["hook"]["id"])
        with connection.cursor() as cursor:
            cursor.execute("SELECT auth_token FROM api_outboundwebhook WHERE name = %s", [rule.name])
            encrypted = cursor.fetchone()[0]
        assert encrypted and token not in encrypted
        assert rule.auth_token == token
        assert rule.default_headers()["Authorization"] == token
        assert rule.keep_last_response
        page = self.client.get("/admin/rules/", HTTP_HOST=host)
        assert page.status_code == 200
        assert token.encode() not in page.content
        response = self.client.post(
            "/admin/rules/save/",
            {**payload, "id": str(rule.pk), "auth_token": ""},
            content_type="application/json",
            HTTP_HOST=host,
        )
        assert response.status_code == 200, response.content
        rule.refresh_from_db()
        assert rule.auth_token == token

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
