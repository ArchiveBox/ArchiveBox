from django.test import TestCase


class TestSignalWebhooksSettings(TestCase):
    def test_task_handler_runs_after_transaction_commit(self):
        from signal_webhooks.settings import webhook_settings

        assert webhook_settings.TASK_HANDLER.__name__ == "transaction_on_commit_task_handler"
