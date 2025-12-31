"""
Tests for admin snapshot views and search functionality.

Tests cover:
- Admin snapshot list view
- Admin grid view
- Search functionality (both admin and public)
- Snapshot progress statistics
"""

import pytest
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.django_db


User = get_user_model()


@pytest.fixture
def admin_user(db):
    """Create admin user for tests."""
    return User.objects.create_superuser(
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
        response = client.get(url)

        assert response.status_code == 200

    def test_list_view_with_snapshots(self, client, admin_user, snapshot):
        """Test list view with snapshots displays them."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url)

        assert response.status_code == 200
        assert b'example.com' in response.content

    def test_grid_view_renders(self, client, admin_user):
        """Test that the grid view renders successfully."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:grid')
        response = client.get(url)

        assert response.status_code == 200

    def test_view_mode_switcher_present(self, client, admin_user):
        """Test that view mode switcher is present."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url)

        assert response.status_code == 200
        # Check for view mode toggle elements
        assert b'snapshot-view-mode' in response.content
        assert b'snapshot-view-list' in response.content
        assert b'snapshot-view-grid' in response.content


class TestAdminSnapshotSearch:
    """Tests for admin snapshot search functionality."""

    def test_search_by_url(self, client, admin_user, snapshot):
        """Test searching snapshots by URL."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, {'q': 'example.com'})

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
        response = client.get(url, {'q': 'Unique Title'})

        assert response.status_code == 200

    def test_search_by_tag(self, client, admin_user, snapshot, db):
        """Test searching snapshots by tag."""
        from archivebox.core.models import Tag
        tag = Tag.objects.create(name='test-search-tag')
        snapshot.tags.add(tag)

        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, {'q': 'test-search-tag'})

        assert response.status_code == 200

    def test_empty_search(self, client, admin_user):
        """Test empty search returns all snapshots."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, {'q': ''})

        assert response.status_code == 200

    def test_no_results_search(self, client, admin_user):
        """Test search with no results."""
        client.login(username='testadmin', password='testpassword')
        url = reverse('admin:core_snapshot_changelist')
        response = client.get(url, {'q': 'nonexistent-url-xyz789'})

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
        response = client.get('/public/', {'q': 'public-example.com'})
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_by_title(self, client, public_snapshot):
        """Test public search by title."""
        response = client.get('/public/', {'q': 'Public Example'})
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_query_type_meta(self, client, public_snapshot):
        """Test public search with query_type=meta."""
        response = client.get('/public/', {'q': 'example', 'query_type': 'meta'})
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_query_type_url(self, client, public_snapshot):
        """Test public search with query_type=url."""
        response = client.get('/public/', {'q': 'public-example.com', 'query_type': 'url'})
        assert response.status_code == 200

    @override_settings(PUBLIC_INDEX=True)
    def test_public_search_query_type_title(self, client, public_snapshot):
        """Test public search with query_type=title."""
        response = client.get('/public/', {'q': 'Website', 'query_type': 'title'})
        assert response.status_code == 200
