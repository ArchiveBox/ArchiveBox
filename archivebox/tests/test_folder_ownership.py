import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from archivebox.core.models import Folder
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db
HOST = {"HTTP_HOST": ADMIN_TEST_HOST}


def test_inline_folder_records_creator_and_preserves_it_on_edit(admin_client, admin_user):
    other = get_user_model().objects.create_user(username="other-folder-owner")
    response = admin_client.post("/admin/core/folder/save/", {"name": "Reading", "created_by": other.pk}, **HOST)
    assert response.status_code == 200, response.content
    folder = Folder.objects.get(pk=response.json()["id"])
    assert folder.created_by_id == admin_user.pk
    folder.created_by = other
    folder.save()
    response = admin_client.post(
        "/admin/core/folder/save/",
        {"folder_id": folder.pk, "name": "Read later", "created_by": admin_user.pk},
        **HOST,
    )
    assert response.status_code == 200, response.content
    folder.refresh_from_db()
    assert folder.created_by_id == other.pk
    other.delete()
    folder.refresh_from_db()
    assert folder.created_by_id is None
    assert folder.name == "Read later"


def test_admin_folder_add_records_creator(admin_client, admin_user):
    response = admin_client.post("/admin/core/folder/add/", {"name": "Admin folder", "position": 0, "_save": "Save"}, **HOST)
    assert response.status_code == 302, response.content
    assert Folder.objects.get(name="Admin folder").created_by_id == admin_user.pk


def test_folder_paths_are_unique_not_names(admin_client):
    a = Folder.objects.create(name="A")
    b = Folder.objects.create(name="B")
    for parent in [a, b]:
        response = admin_client.post("/admin/core/folder/save/", {"name": "C", "parent": parent.pk}, **HOST)
        assert response.status_code == 200, response.content
    response = admin_client.post("/admin/core/folder/save/", {"name": "C", "parent": a.pk}, **HOST)
    assert response.status_code == 400
    response = admin_client.post("/admin/core/folder/save/", {"name": " A "}, **HOST)
    assert response.status_code == 400
    c = Folder.objects.get(parent=b, name="C")
    response = admin_client.post("/admin/core/folder/move/", {"folder_id": c.pk, "target_id": a.pk, "placement": "inside"}, **HOST)
    assert response.status_code == 400
    c.refresh_from_db()
    assert c.parent_id == b.pk
    assert Folder.objects.filter(name="C").count() == 2


def test_database_enforces_root_and_sibling_uniqueness():
    root = Folder.objects.create(name="A")
    Folder.objects.create(name="C", parent=root)
    for name, parent in [("A", None), ("C", root)]:
        with pytest.raises(IntegrityError), transaction.atomic():
            Folder.objects.bulk_create([Folder(name=name, parent=parent)])
    assert set(Folder.objects.values_list("name", flat=True)) == {"A", "C", "📥 Inbox"}
