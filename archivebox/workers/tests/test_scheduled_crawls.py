from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.workers.orchestrator import Orchestrator


class TestScheduledCrawlMaterialization(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='schedule-user',
            password='password',
        )

    def _create_due_schedule(self) -> CrawlSchedule:
        template = Crawl.objects.create(
            urls='https://example.com/feed.xml',
            max_depth=1,
            tags_str='scheduled',
            label='Scheduled Feed',
            notes='template',
            created_by=self.user,
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        schedule = CrawlSchedule.objects.create(
            template=template,
            schedule='daily',
            is_enabled=True,
            label='Scheduled Feed',
            notes='template',
            created_by=self.user,
        )
        past = timezone.now() - timedelta(days=2)
        Crawl.objects.filter(pk=template.pk).update(created_at=past, modified_at=past)
        template.refresh_from_db()
        schedule.refresh_from_db()
        return schedule

    def test_global_orchestrator_materializes_due_schedule(self):
        schedule = self._create_due_schedule()

        orchestrator = Orchestrator(exit_on_idle=False)
        orchestrator._materialize_due_schedules()

        scheduled_crawls = Crawl.objects.filter(schedule=schedule).order_by('created_at')
        self.assertEqual(scheduled_crawls.count(), 2)

        queued_crawl = scheduled_crawls.last()
        self.assertEqual(queued_crawl.status, Crawl.StatusChoices.QUEUED)
        self.assertEqual(queued_crawl.urls, 'https://example.com/feed.xml')
        self.assertEqual(queued_crawl.max_depth, 1)
        self.assertEqual(queued_crawl.tags_str, 'scheduled')

    def test_one_shot_orchestrator_does_not_materialize_due_schedule(self):
        schedule = self._create_due_schedule()

        Orchestrator(exit_on_idle=True)._materialize_due_schedules()
        self.assertEqual(Crawl.objects.filter(schedule=schedule).count(), 1)

        Orchestrator(exit_on_idle=False, crawl_id=str(schedule.template_id))._materialize_due_schedules()
        self.assertEqual(Crawl.objects.filter(schedule=schedule).count(), 1)
