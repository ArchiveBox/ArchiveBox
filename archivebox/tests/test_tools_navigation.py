import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from lxml.html import fromstring

from archivebox.tests.conftest import ADMIN_TEST_HOST


@pytest.mark.django_db
def test_shared_tools_menu_labels_and_personas_access(admin_client, django_user_model):
    def links():
        response = admin_client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        menu = fromstring(response.content).xpath('//details[contains(@class,"library-tools")]/div')[0]
        return [(link.text_content().strip(), link.get("href")) for link in menu.xpath("./a")]

    admin_links = links()
    assert ("Crawl Jobs", reverse("admin:crawls_crawl_changelist")) in admin_links
    assert ("Scheduled Crawls", reverse("admin:crawls_crawlschedule_changelist")) in admin_links
    assert ("Crawls", reverse("admin:crawls_crawl_changelist")) not in admin_links
    assert [label for label, _ in admin_links][-2:] == ["Personas", "System Settings"]
    assert ("Personas", reverse("admin:personas_persona_changelist")) in admin_links

    staff = django_user_model.objects.create_user(username="staff-tools", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_snapshot"))
    admin_client.force_login(staff)
    staff_labels = [label for label, _ in links()]
    assert "Crawl Jobs" in staff_labels and "Scheduled Crawls" in staff_labels
    assert "Personas" not in staff_labels and "System Settings" not in staff_labels
