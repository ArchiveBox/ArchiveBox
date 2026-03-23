"""
Tests for admin snapshot views and search functionality.

Tests cover:
- Admin snapshot list view
- Admin grid view
- Search functionality (both admin and public)
- Snapshot progress statistics
"""

import pytest
import uuid
from typing import cast
from django.test import override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import UserManager
from django.utils import timezone

pytestmark = pytest.mark.django_db


User = get_user_model()
ADMIN_HOST = 'admin.archivebox.localhost:8000'
PUBLIC_HOST = 'public.archivebox.localhost:8000'


@pytest.fixture
def admin_user(db):
    """Create admin user for tests."""
    return cast(UserManager, User.objects).create_superuser(
        username='testadmin',
        email='admin@test.com',
        password='testpassword'
    )


@pytest.fixture
def crawl(admin_user, db):
    """Create test crawl."""
    from archivebox.crawls.models import Crawl
    return Crawl.objects.create(
        urls='https://example.com',
        created_by=admin_user,
    )


@pytest.fixture
def snapshot(crawl, db):
    """Create test snapshot."""
    from archivebox.core.models import Snapshot
    return Snapshot.objects.create(
        url='https://example.com',
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )


class TestSnapshotProgressStats:
    """Tests for Snapshot.get_progress_stats() method."""

    def test_get_progress_stats_empty(self, snapshot):
        """Test progress stats with no archive results."""
        stats = snapshot.get_progress_stats()

        assert stats['total'] == 0
        assert stats['succeeded'] == 0
        assert stats['failed'] == 0
        assert stats['running'] == 0
        assert stats['pending'] == 0
        assert stats['percent'] == 0
        assert stats['output_size'] == 0
        assert stats['is_sealed'] is False

    def test_get_progress_stats_with_results(self, snapshot, db):
        """Test progress stats with various archive result statuses."""
        from archivebox.core.models import ArchiveResult

        # Create some archive results
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin='wget',
            status='succeeded',
            output_size=1000,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin='screenshot',
            status='succeeded',
            output_size=2000,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin='pdf',
            status='failed',
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin='readability',
            status='started',
        )

        stats = snapshot.get_progress_stats()

        assert stats['total'] == 4
        assert stats['succeeded'] == 2
        assert stats['failed'] == 1
        assert stats['running'] == 1
        assert stats['output_size'] == 3000
        assert stats['percent'] == 75  # (2 succeeded + 1 failed) / 4 total

    def test_get_progress_stats_sealed(self, snapshot):
        """Test progress stats for sealed snapshot."""
        from archivebox.core.models import Snapshot
        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.save()

        stats = snapshot.get_progress_stats()
        assert stats['is_sealed'] is True


class TestAdminSnapshotListView:
    """Tests for the admin snapshot list view."""

    def test_list_view_renders(self, client, admin_user):
        """Test that the list view renders successfully."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_list_view_with_snapshots(self, client, admin_user, snapshot):
        """Test list view with snapshots displays them."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b'example.com' in response.content

    def test_list_view_avoids_legacy_title_fallbacks(self, client, admin_user, snapshot, monkeypatch):
        """Title-less snapshots should render without touching history-based fallback paths."""
        from archivebox.core.models import Snapshot

        Snapshot.objects.filter(pk=snapshot.pk).update(title='')

        def _latest_title_should_not_be_used(self):
            raise AssertionError('admin changelist should not access Snapshot.latest_title')

        def _history_should_not_be_used(self):
            raise AssertionError('admin changelist should not access Snapshot.history')

        monkeypatch.setattr(Snapshot, 'latest_title', property(_latest_title_should_not_be_used), raising=False)
        monkeypatch.setattr(Snapshot, 'history', property(_history_should_not_be_used), raising=False)

        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b'example.com' in response.content

    def test_list_view_avoids_output_dir_lookups(self, client, admin_user, snapshot, monkeypatch):
        """Changelist links should render without probing snapshot paths on disk."""
        from archivebox.core.models import Snapshot

        def _output_dir_should_not_be_used(self):
            raise AssertionError('admin changelist should not access Snapshot.output_dir')

        monkeypatch.setattr(Snapshot, 'output_dir', property(_output_dir_should_not_be_used), raising=False)

        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b'example.com' in response.content

    def test_grid_view_renders(self, client, admin_user):
        """Test that the grid view renders successfully."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:grid')
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_view_mode_switcher_present(self, client, admin_user):
        """Test that view mode switcher is present."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        # Check for view mode toggle elements
        assert b'snapshot-view-mode' in response.content
        assert b'snapshot-view-list' in response.content
        assert b'snapshot-view-grid' in response.content

    def test_binary_change_view_renders(self, client, admin_user, db):
        """Binary admin change form should load without FieldError."""
        from archivebox.machine.models import Machine, Binary

        machine = Machine.objects.create(
            guid=f'test-guid-{uuid.uuid4()}',
            hostname='test-host',
            hw_in_docker=False,
            hw_in_vm=False,
            hw_manufacturer='Test',
            hw_product='Test Product',
            hw_uuid=f'test-hw-{uuid.uuid4()}',
            os_arch='x86_64',
            os_family='darwin',
            os_platform='darwin',
            os_release='test',
            os_kernel='test-kernel',
            stats={},
        )
        binary = Binary.objects.create(
            machine=machine,
            name='gallery-dl',
            binproviders='env',
            binprovider='env',
            abspath='/opt/homebrew/bin/gallery-dl',
            version='1.26.9',
            sha256='abc123',
            status=Binary.StatusChoices.INSTALLED,
        )

        client.login(username='testadmin', password='testpassword')
        url = f'/admin/machine/binary/{binary.pk}/change/'
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b'gallery-dl' in response.content

    def test_change_view_renders_real_redo_failed_action(self, client, admin_user, snapshot):
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_change', args=[snapshot.pk])
        response = client.get(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert f'/admin/core/snapshot/{snapshot.pk}/redo-failed/'.encode() in response.content

    def test_redo_failed_action_requeues_snapshot(self, client, admin_user, snapshot, monkeypatch):
        import archivebox.core.admin_snapshots as admin_snapshots

        queued = []

        def fake_bg_archive_snapshot(obj, overwrite=False, methods=None):
            queued.append((str(obj.pk), overwrite, methods))
            return 1

        monkeypatch.setattr(admin_snapshots, 'bg_archive_snapshot', fake_bg_archive_snapshot)

        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_redo_failed', args=[snapshot.pk])
        response = client.post(url, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 302
        assert queued == [(str(snapshot.pk), False, None)]
        assert response['Location'].endswith(f'/admin/core/snapshot/{snapshot.pk}/change/')


class TestArchiveResultAdminListView:
    def test_list_view_renders_readonly_tags_and_noresults_status(self, client, admin_user, snapshot):
        from archivebox.core.models import ArchiveResult, Tag

        tag = Tag.objects.create(name='Alpha Research')
        snapshot.tags.add(tag)
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin='title',
            status=ArchiveResult.StatusChoices.NORESULTS,
            output_str='No title found',
        )

        client.login(username='testadmin', password='testpassword')
        response = client.get(reverse('admin:core_archiveresult_changelist'), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        assert b'Alpha Research' in response.content
        assert b'tag-editor-inline readonly' in response.content
        assert b'No Results' in response.content

    def test_archiveresult_model_has_no_retry_at_field(self):
        from archivebox.core.models import ArchiveResult

        assert 'retry_at' not in {field.name for field in ArchiveResult._meta.fields}


class TestLiveProgressView:
    def test_live_progress_routes_crawl_process_rows_to_crawl_setup(self, client, admin_user, snapshot, db):
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=43210,
            cmd=['/plugins/chrome/on_Crawl__91_chrome_wait.js', '--url=https://example.com'],
            env={
                'CRAWL_ID': str(snapshot.crawl_id),
                'SNAPSHOT_ID': str(snapshot.id),
            },
            started_at=timezone.now(),
        )

        client.login(username='testadmin', password='testpassword')
        response = client.get(reverse('live_progress'), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload['active_crawls'] if crawl['id'] == str(snapshot.crawl_id))
        setup_entry = next(item for item in active_crawl['setup_plugins'] if item['source'] == 'process')
        active_snapshot = next(item for item in active_crawl['active_snapshots'] if item['id'] == str(snapshot.id))
        assert setup_entry['label'] == 'chrome wait'
        assert setup_entry['status'] == 'started'
        assert active_crawl['worker_pid'] == 43210
        assert active_snapshot['all_plugins'] == []

    def test_live_progress_uses_snapshot_process_rows_before_archiveresults(self, client, admin_user, snapshot, db):
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=43211,
            cmd=['/plugins/title/on_Snapshot__10_title.py', '--url=https://example.com'],
            env={
                'CRAWL_ID': str(snapshot.crawl_id),
                'SNAPSHOT_ID': str(snapshot.id),
            },
            started_at=timezone.now(),
        )

        client.login(username='testadmin', password='testpassword')
        response = client.get(reverse('live_progress'), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload['active_crawls'] if crawl['id'] == str(snapshot.crawl_id))
        active_snapshot = next(item for item in active_crawl['active_snapshots'] if item['id'] == str(snapshot.id))
        assert active_snapshot['all_plugins'][0]['source'] == 'process'
        assert active_snapshot['all_plugins'][0]['label'] == 'title'
        assert active_snapshot['all_plugins'][0]['status'] == 'started'
        assert active_snapshot['worker_pid'] == 43211

    def test_live_progress_merges_process_rows_with_archiveresults_when_present(self, client, admin_user, snapshot, db):
        import archivebox.machine.models as machine_models
        from archivebox.core.models import ArchiveResult
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=54321,
            cmd=['/plugins/chrome/on_Snapshot__11_chrome_wait.js', '--url=https://example.com'],
            env={
                'CRAWL_ID': str(snapshot.crawl_id),
                'SNAPSHOT_ID': str(snapshot.id),
            },
            started_at=timezone.now(),
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin='title',
            status=ArchiveResult.StatusChoices.STARTED,
        )

        client.login(username='testadmin', password='testpassword')
        response = client.get(reverse('live_progress'), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload['active_crawls'] if crawl['id'] == str(snapshot.crawl_id))
        active_snapshot = next(item for item in active_crawl['active_snapshots'] if item['id'] == str(snapshot.id))
        sources = {item['source'] for item in active_snapshot['all_plugins']}
        plugins = {item['plugin'] for item in active_snapshot['all_plugins']}
        assert sources == {'archiveresult', 'process'}
        assert 'title' in plugins
        assert 'chrome' in plugins

    def test_live_progress_omits_pid_for_exited_process_rows(self, client, admin_user, snapshot, db):
        import archivebox.machine.models as machine_models
        from archivebox.machine.models import Machine, Process

        machine_models._CURRENT_MACHINE = None
        machine = Machine.current()
        Process.objects.create(
            machine=machine,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.EXITED,
            exit_code=0,
            pid=99999,
            cmd=['/plugins/title/on_Snapshot__10_title.py', '--url=https://example.com'],
            env={
                'CRAWL_ID': str(snapshot.crawl_id),
                'SNAPSHOT_ID': str(snapshot.id),
            },
            started_at=timezone.now(),
            ended_at=timezone.now(),
        )

        client.login(username='testadmin', password='testpassword')
        response = client.get(reverse('live_progress'), HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        payload = response.json()
        active_crawl = next(crawl for crawl in payload['active_crawls'] if crawl['id'] == str(snapshot.crawl_id))
        active_snapshot = next(item for item in active_crawl['active_snapshots'] if item['id'] == str(snapshot.id))
        process_entry = next(item for item in active_snapshot['all_plugins'] if item['source'] == 'process')
        assert process_entry['status'] == 'succeeded'
        assert 'pid' not in process_entry


class TestAdminSnapshotSearch:
    """Tests for admin snapshot search functionality."""

    def test_search_by_url(self, client, admin_user, snapshot):
        """Test searching snapshots by URL."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, {'q': 'example.com'}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200
        # The search should find the example.com snapshot
        assert b'example.com' in response.content

    def test_search_by_title(self, client, admin_user, crawl, db):
        """Test searching snapshots by title."""
        from archivebox.core.models import Snapshot
        Snapshot.objects.create(
            url='https://example.com/titled',
            title='Unique Title For Testing',
            crawl=crawl,
        )

        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, {'q': 'Unique Title'}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_search_by_tag(self, client, admin_user, snapshot, db):
        """Test searching snapshots by tag."""
        from archivebox.core.models import Tag
        tag = Tag.objects.create(name='test-search-tag')
        snapshot.tags.add(tag)

        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, {'q': 'test-search-tag'}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_empty_search(self, client, admin_user):
        """Test empty search returns all snapshots."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, {'q': ''}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200

    def test_no_results_search(self, client, admin_user):
        """Test search with no results."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, {'q': 'nonexistent-url-xyz789'}, HTTP_HOST=ADMIN_HOST)

        assert response.status_code == 200


class TestPublicIndexSearch:
    """Tests for public index search functionality."""

    @pytest.fixture
    def public_snapshot(self, crawl, db):
        """Create sealed snapshot for public index."""
        from archivebox.core.models import Snapshot
        return Snapshot.objects.create(
            url='https://public-example.com',
            title='Public Example Website',
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
        )

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_by_url(self, client, public_snapshot):
        """Test public search by URL."""
        response = client.get('/public/', {'q': 'public-example.com'}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_by_title(self, client, public_snapshot):
        """Test public search by title."""
        response = client.get('/public/', {'q': 'Public Example'}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_query_type_meta(self, client, public_snapshot):
        """Test public search with query_type=meta."""
        response = client.get('/public/', {'q': 'example', 'query_type': 'meta'}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_query_type_url(self, client, public_snapshot):
        """Test public search with query_type=url."""
        response = client.get('/public/', {'q': 'public-example.com', 'query_type': 'url'}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_query_type_title(self, client, public_snapshot):
        """Test public search with query_type=title."""
        response = client.get('/public/', {'q': 'Website', 'query_type': 'title'}, HTTP_HOST=PUBLIC_HOST)
        assert response.status_code == 200
