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
        assert f"/api/v1/core/snapshots.rss?created_by={admin_user.username}&amp;limit=50&amp;api_key=".encode() in response.content
        assert b"RSS" in response.content

    def test_user_admin_change_view_renders_rss_feed_link(self, client, admin_user):
        client.force_login(admin_user)
        response = client.get(reverse("admin:auth_user_change", args=[admin_user.pk]), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Snapshot Feed" in response.content
        assert f"/api/v1/core/snapshots.rss?created_by={admin_user.username}&amp;limit=50&amp;api_key=".encode() in response.content
