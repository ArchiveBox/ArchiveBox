"""Tests for the core views, especially AddView."""

import os
import django

# Set up Django before importing any Django-dependent modules
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.settings')
django.setup()

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from archivebox.crawls.models import Crawl, CrawlSchedule
from archivebox.core.models import Tag


class AddViewTests(TestCase):
    """Tests for the AddView (crawl creation form)."""

    def setUp(self):
        """Set up test user and client."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        self.client.login(username='testuser', password='testpass123')
        self.add_url = reverse('add')

    def test_add_view_get_requires_auth(self):
        """Test that GET /add requires authentication."""
        self.client.logout()
        response = self.client.get(self.add_url)
        # Should redirect to login or show 403/404
        self.assertIn(response.status_code, [302, 403, 404])

    def test_add_view_get_shows_form(self):
        """Test that GET /add shows the form with all fields."""
        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)

        # Check that form fields are present
        self.assertContains(response, 'name="url"')
        self.assertContains(response, 'name="tag"')
        self.assertContains(response, 'name="depth"')
        self.assertContains(response, 'name="notes"')
        self.assertContains(response, 'name="schedule"')
        self.assertContains(response, 'name="persona"')
        self.assertContains(response, 'name="overwrite"')
        self.assertContains(response, 'name="update"')
        self.assertContains(response, 'name="index_only"')

        # Check for plugin groups
        self.assertContains(response, 'name="chrome_plugins"')
        self.assertContains(response, 'name="archiving_plugins"')
        self.assertContains(response, 'name="parsing_plugins"')

    def test_add_view_shows_tag_autocomplete(self):
        """Test that tag autocomplete datalist is rendered."""
        # Create some tags
        Tag.objects.create(name='test-tag-1')
        Tag.objects.create(name='test-tag-2')

        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)

        # Check for datalist with tags
        self.assertContains(response, 'id="tag-datalist"')
        self.assertContains(response, 'test-tag-1')
        self.assertContains(response, 'test-tag-2')

    def test_add_view_shows_plugin_presets(self):
        """Test that plugin preset buttons are rendered."""
        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, 'Quick Archive')
        self.assertContains(response, 'Full Chrome')
        self.assertContains(response, 'Text Only')
        self.assertContains(response, 'Select All')
        self.assertContains(response, 'Clear All')

    def test_add_view_shows_links_to_resources(self):
        """Test that helpful links are present."""
        response = self.client.get(self.add_url)
        self.assertEqual(response.status_code, 200)

        # Link to plugin documentation
        self.assertContains(response, '/admin/environment/plugins/')

        # Link to create new persona
        self.assertContains(response, '/admin/personas/persona/add/')

    def test_add_basic_crawl_without_schedule(self):
        """Test creating a basic crawl without a schedule."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com\nhttps://example.org',
            'tag': 'test-tag',
            'depth': '0',
            'notes': 'Test crawl notes',
        })

        # Should redirect to crawl admin page
        self.assertEqual(response.status_code, 302)

        # Check that crawl was created
        self.assertEqual(Crawl.objects.count(), 1)
        crawl = Crawl.objects.first()

        self.assertIn('https://example.com', crawl.urls)
        self.assertIn('https://example.org', crawl.urls)
        self.assertEqual(crawl.tags_str, 'test-tag')
        self.assertEqual(crawl.max_depth, 0)
        self.assertEqual(crawl.notes, 'Test crawl notes')
        self.assertEqual(crawl.created_by, self.user)

        # No schedule should be created
        self.assertIsNone(crawl.schedule)
        self.assertEqual(CrawlSchedule.objects.count(), 0)

    def test_add_crawl_with_schedule(self):
        """Test creating a crawl with a repeat schedule."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com',
            'tag': 'scheduled',
            'depth': '1',
            'notes': 'Daily crawl',
            'schedule': 'daily',
        })

        self.assertEqual(response.status_code, 302)

        # Check that crawl and schedule were created
        self.assertEqual(Crawl.objects.count(), 1)
        self.assertEqual(CrawlSchedule.objects.count(), 1)

        crawl = Crawl.objects.first()
        schedule = CrawlSchedule.objects.first()

        self.assertEqual(crawl.schedule, schedule)
        self.assertEqual(schedule.template, crawl)
        self.assertEqual(schedule.schedule, 'daily')
        self.assertTrue(schedule.is_enabled)
        self.assertEqual(schedule.created_by, self.user)

    def test_add_crawl_with_cron_schedule(self):
        """Test creating a crawl with a cron format schedule."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com',
            'depth': '0',
            'schedule': '0 */6 * * *',  # Every 6 hours
        })

        self.assertEqual(response.status_code, 302)

        schedule = CrawlSchedule.objects.first()
        self.assertEqual(schedule.schedule, '0 */6 * * *')

    def test_add_crawl_with_plugins(self):
        """Test creating a crawl with specific plugins selected."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com',
            'depth': '0',
            'chrome_plugins': ['screenshot', 'dom'],
            'archiving_plugins': ['wget'],
        })

        self.assertEqual(response.status_code, 302)

        crawl = Crawl.objects.first()
        plugins = crawl.config.get('PLUGINS', '')

        # Should contain the selected plugins
        self.assertIn('screenshot', plugins)
        self.assertIn('dom', plugins)
        self.assertIn('wget', plugins)

    def test_add_crawl_with_depth_range(self):
        """Test creating crawls with different depth values (0-4)."""
        for depth in range(5):
            response = self.client.post(self.add_url, {
                'url': f'https://example{depth}.com',
                'depth': str(depth),
            })

            self.assertEqual(response.status_code, 302)

        self.assertEqual(Crawl.objects.count(), 5)

        for i, crawl in enumerate(Crawl.objects.order_by('created_at')):
            self.assertEqual(crawl.max_depth, i)

    def test_add_crawl_with_advanced_options(self):
        """Test creating a crawl with advanced options."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com',
            'depth': '0',
            'persona': 'CustomPersona',
            'overwrite': True,
            'update': True,
            'index_only': True,
        })

        self.assertEqual(response.status_code, 302)

        crawl = Crawl.objects.first()
        config = crawl.config

        self.assertEqual(config.get('DEFAULT_PERSONA'), 'CustomPersona')
        self.assertEqual(config.get('OVERWRITE'), True)
        self.assertEqual(config.get('ONLY_NEW'), False)  # opposite of update
        self.assertEqual(config.get('INDEX_ONLY'), True)

    def test_add_crawl_with_custom_config(self):
        """Test creating a crawl with custom config overrides."""
        # Note: Django test client can't easily POST the KeyValueWidget format,
        # so this test would need to use the form directly or mock the cleaned_data
        # For now, we'll skip this test or mark it as TODO
        pass

    def test_add_empty_urls_fails(self):
        """Test that submitting without URLs fails validation."""
        response = self.client.post(self.add_url, {
            'url': '',
            'depth': '0',
        })

        # Should show form again with errors, not redirect
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response, 'form', 'url', 'This field is required.')

    def test_add_invalid_urls_fails(self):
        """Test that invalid URLs fail validation."""
        response = self.client.post(self.add_url, {
            'url': 'not-a-url',
            'depth': '0',
        })

        # Should show form again with errors
        self.assertEqual(response.status_code, 200)
        # Check for validation error (URL regex should fail)
        self.assertContains(response, 'error')

    def test_add_success_message_without_schedule(self):
        """Test that success message is shown without schedule link."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com\nhttps://example.org',
            'depth': '0',
        }, follow=True)

        # Check success message mentions crawl creation
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        message_text = str(messages[0])

        self.assertIn('Created crawl with 2 starting URL', message_text)
        self.assertIn('View Crawl', message_text)
        self.assertNotIn('scheduled to repeat', message_text)

    def test_add_success_message_with_schedule(self):
        """Test that success message includes schedule link."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com',
            'depth': '0',
            'schedule': 'weekly',
        }, follow=True)

        # Check success message mentions schedule
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        message_text = str(messages[0])

        self.assertIn('Created crawl', message_text)
        self.assertIn('scheduled to repeat weekly', message_text)
        self.assertIn('View Crawl', message_text)

    def test_add_crawl_creates_source_file(self):
        """Test that crawl creation saves URLs to sources file."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com',
            'depth': '0',
        })

        self.assertEqual(response.status_code, 302)

        # Check that source file was created in sources/ directory
        from archivebox.config import CONSTANTS
        sources_dir = CONSTANTS.SOURCES_DIR

        # Should have created a source file
        source_files = list(sources_dir.glob('*__web_ui_add_by_user_*.txt'))
        self.assertGreater(len(source_files), 0)

    def test_multiple_tags_are_saved(self):
        """Test that multiple comma-separated tags are saved."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com',
            'depth': '0',
            'tag': 'tag1,tag2,tag3',
        })

        self.assertEqual(response.status_code, 302)

        crawl = Crawl.objects.first()
        self.assertEqual(crawl.tags_str, 'tag1,tag2,tag3')

    def test_crawl_redirects_to_admin_change_page(self):
        """Test that successful submission redirects to crawl admin page."""
        response = self.client.post(self.add_url, {
            'url': 'https://example.com',
            'depth': '0',
        })

        crawl = Crawl.objects.first()
        expected_redirect = f'/admin/crawls/crawl/{crawl.id}/change/'

        self.assertRedirects(response, expected_redirect, fetch_redirect_response=False)
