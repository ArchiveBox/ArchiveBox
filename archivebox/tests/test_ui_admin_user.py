"""User admin UI tests."""

import pytest
from html import unescape
from urllib.parse import parse_qs, urlsplit
import re
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


class TestUserAdmin:
    def test_user_admin_list_view_renders(self, client, admin_user):
        client.force_login(admin_user)
        response = client.get(reverse("admin:auth_user_changelist"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"Select user to change" in response.content
        for format in ("csv", "jsonl"):
            path = reverse("admin:core_snapshot_feed") if format == "rss" else reverse("admin:core_snapshot_export", args=[format])
            assert f'href="{path}?crawl__created_by__id__exact={admin_user.pk}" data-export-format="{format}"'.encode() in response.content
        links = {
            format: unescape(url)
            for url, format in re.findall(r'href="([^"]+)" data-export-format="(rss|rss_public)"', response.content.decode())
        }
        assert parse_qs(urlsplit(links["rss"]).query)["api_key"]
        assert parse_qs(urlsplit(links["rss_public"]).query)["public_only"] == ["1"]
        assert "api_key" not in parse_qs(urlsplit(links["rss_public"]).query)
        assert b"/api/v1/core/snapshots.rss?" not in response.content
        assert b"RSS" in response.content

    def test_user_admin_change_view_renders_private_and_public_exports(self, client, admin_user):
        client.force_login(admin_user)
        response = client.get(reverse("admin:auth_user_change", args=[admin_user.pk]), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        for format in ("csv", "jsonl"):
            path = reverse("admin:core_snapshot_feed") if format == "rss" else reverse("admin:core_snapshot_export", args=[format])
            assert f'href="{path}?crawl__created_by__id__exact={admin_user.pk}" data-export-format="{format}"'.encode() in response.content
        links = {
            format: unescape(url)
            for url, format in re.findall(r'href="([^"]+)" data-export-format="(rss|rss_public)"', response.content.decode())
        }
        assert parse_qs(urlsplit(links["rss"]).query)["api_key"]
        assert parse_qs(urlsplit(links["rss_public"]).query)["public_only"] == ["1"]
        assert "api_key" not in parse_qs(urlsplit(links["rss_public"]).query)
        assert b"/api/v1/core/snapshots.rss?" not in response.content
