import os
import django
from io import StringIO
from types import SimpleNamespace

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.settings')
django.setup()

from django.contrib.auth.models import User
from django.test import TestCase

from archivebox.api.v1_cli import ScheduleCommandSchema, cli_schedule
from archivebox.crawls.models import CrawlSchedule


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
