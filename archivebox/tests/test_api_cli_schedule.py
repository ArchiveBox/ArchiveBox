from io import StringIO

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from archivebox.api.v1_cli import ScheduleCommandSchema, cli_schedule
from archivebox.crawls.models import CrawlSchedule

User = get_user_model()


class CLIScheduleAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="api-user",
            password="testpass123",
            email="api@example.com",
        )

    def test_schedule_api_creates_schedule(self):
        request = RequestFactory().post("/api/v1/cli/schedule")
        request.user = self.user
        setattr(request, "stdout", StringIO())
        setattr(request, "stderr", StringIO())
        args = ScheduleCommandSchema(
            every="daily",
            import_path="https://example.com/feed.xml",
            quiet=True,
        )

        response = cli_schedule(request, args)

        self.assertTrue(response["success"])
        self.assertEqual(response["result_format"], "json")
        self.assertEqual(CrawlSchedule.objects.count(), 1)
        self.assertEqual(len(response["result"]["created_schedule_ids"]), 1)
