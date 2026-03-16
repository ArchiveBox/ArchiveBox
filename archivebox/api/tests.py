import importlib
from io import StringIO
from types import SimpleNamespace

from archivebox.config.django import setup_django

setup_django()

User = importlib.import_module('django.contrib.auth.models').User
TestCase = importlib.import_module('django.test').TestCase
api_v1_cli = importlib.import_module('archivebox.api.v1_cli')
ScheduleCommandSchema = api_v1_cli.ScheduleCommandSchema
cli_schedule = api_v1_cli.cli_schedule
CrawlSchedule = importlib.import_module('archivebox.crawls.models').CrawlSchedule


class CLIScheduleAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='api-user',
            password='testpass123',
            email='api@example.com',
        )

    def test_schedule_api_creates_schedule(self):
        request = SimpleNamespace(
            user=self.user,
            stdout=StringIO(),
            stderr=StringIO(),
        )
        args = ScheduleCommandSchema(
            every='daily',
            import_path='https://example.com/feed.xml',
            quiet=True,
        )

        response = cli_schedule(request, args)

        self.assertTrue(response['success'])
        self.assertEqual(response['result_format'], 'json')
        self.assertEqual(CrawlSchedule.objects.count(), 1)
        self.assertEqual(len(response['result']['created_schedule_ids']), 1)
