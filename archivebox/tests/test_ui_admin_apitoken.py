"""API token admin UI tests."""

import pytest
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


class TestAPITokenAdmin:
    def test_api_token_admin_list_view_renders(self, client, admin_user):
        client.force_login(admin_user)
        response = client.get(reverse("admin:api_apitoken_changelist"), HTTP_HOST=ADMIN_TEST_HOST)

        assert response.status_code == 200
        assert b"API Keys" in response.content
