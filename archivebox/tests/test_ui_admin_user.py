"""User admin UI tests."""

import pytest
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


class TestUserAdmin:
    def test_user_admin_list_view_renders(self, client, admin_user):
        client.force_login(admin_user)
        response = client.get(reverse("admin:auth_user_changelist"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Select user to change" in response.content
        for format in ("rss", "csv", "jsonl"):
            path = reverse("admin:core_snapshot_feed") if format == "rss" else reverse("admin:core_snapshot_export", args=[format])
            assert f'href="{path}?crawl__created_by__id__exact={admin_user.pk}" data-export-format="{format}"'.encode() in response.content
        assert b"/api/v1/core/snapshots.rss?" not in response.content
        assert b"RSS" in response.content

    def test_user_admin_change_view_renders_keyless_exports(self, client, admin_user):
        client.force_login(admin_user)
        response = client.get(reverse("admin:auth_user_change", args=[admin_user.pk]), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        for format in ("rss", "csv", "jsonl"):
            path = reverse("admin:core_snapshot_feed") if format == "rss" else reverse("admin:core_snapshot_export", args=[format])
            assert f'href="{path}?crawl__created_by__id__exact={admin_user.pk}" data-export-format="{format}"'.encode() in response.content
        assert b"/api/v1/core/snapshots.rss?" not in response.content
