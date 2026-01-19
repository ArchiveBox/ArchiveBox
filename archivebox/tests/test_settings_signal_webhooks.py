from django.test import TestCase


class TestSignalWebhooksSettings(TestCase):
    def test_task_handler_is_sync_in_tests(self):
        from signal_webhooks.settings import webhook_settings

        assert webhook_settings.TASK_HANDLER.__name__ == "sync_task_handler"
