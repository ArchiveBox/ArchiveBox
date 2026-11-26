"""Anonymous navigation contains only entries backed by listed public captures."""

import pytest

from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import WEB_TEST_HOST


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("mode", ["folders", "tags", "domains"])
def test_anonymous_sidebar_requires_public_listed_snapshots(client, admin_user, settings, mode):
    settings.CONFIG = settings.CONFIG.model_copy(update={"PUBLIC_INDEX": True})
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    rows = []
    for permission, url in [
        ("public", "https://news.ycombinator.com/"),
        ("unlisted", "https://www.python.org/"),
        ("private", "https://www.djangoproject.com/"),
    ]:
        parent = Folder.objects.create(name=f"{permission} parent")
        folder = Folder.objects.create(name=f"{permission} folder", parent=parent)
        smart = Folder.objects.create(name=f"{permission} smart", rules={"field": "url", "lookup": "exact", "value": url})
        tag = Tag.objects.create(name=f"{permission} tag")
        snapshot = Snapshot.objects.create(url=url, crawl=crawl, folder=folder, config={"PERMISSIONS": permission})
        snapshot.tags.add(tag)
        rows.append((snapshot, parent, folder, smart, tag))
    Folder.objects.create(name="empty folder")
    Folder.objects.create(
        name="empty smart",
        rules={"field": "url", "lookup": "exact", "value": "https://github.com/ArchiveBox/ArchiveBox"},
    )
    Tag.objects.create(name="empty tag")
    public, parent, folder, smart, tag = rows[0]

    response = client.get("/public/", {"sidebar": mode}, HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    if mode == "folders":
        assert {item.pk for item in response.context["sidebar_folder_tree"]} == {parent.pk, folder.pk, smart.pk}
    else:
        names = {entry["name"] for entry in response.context["sidebar_entries"]}
        assert names == ({tag.name} if mode == "tags" else {"ycombinator.com"})

    # Initial navigation, sidebar search, and lazy child expansion all use the
    # same public-only rule; an unlisted direct link must not expose its entry.
    for term in ("", "unlisted", "private", "empty"):
        data = client.get("/public/sidebar/", {"sidebar": mode, "sidebar_q": term}, HTTP_HOST=WEB_TEST_HOST)
        assert data.status_code == 200
        html = data.json()["html"]
        for forbidden in (
            "unlisted folder",
            "unlisted smart",
            "unlisted tag",
            "private folder",
            "private smart",
            "private tag",
            "empty folder",
            "empty smart",
            "empty tag",
            "python.org",
            "djangoproject.com",
        ):
            assert forbidden not in html
    if mode == "folders":
        for snapshot, hidden_parent, *_ in rows[1:]:
            data = client.get("/public/sidebar/", {"sidebar": mode, "parent": str(hidden_parent.pk)}, HTTP_HOST=WEB_TEST_HOST)
            assert 'class="folder-row' not in data.json()["html"]

    public.config = {"PERMISSIONS": "unlisted"}
    public.save(update_fields=["config"])
    data = client.get("/public/sidebar/", {"sidebar": mode}, HTTP_HOST=WEB_TEST_HOST)
    assert data.status_code == 200
    assert 'class="folder-row' not in data.json()["html"]
    assert 'class="library-entry' not in data.json()["html"]


@pytest.mark.parametrize("permission", ["private", "unlisted"])
def test_anonymous_sidebar_hides_container_with_no_visible_selected_snapshots(client, admin_user, settings, permission):
    import re

    from archivebox.core.permissions import public_snapshots_queryset

    settings.CONFIG = settings.CONFIG.model_copy(update={"PUBLIC_INDEX": True})
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    parent = Folder.objects.create(name="Limited selection")
    child = Folder.objects.create(name="Captured pages", parent=parent)
    for title, url, visibility in [
        ("A", "https://news.ycombinator.com/", permission),
        ("B", "https://news.ycombinator.com/newest", "public"),
    ]:
        Snapshot.objects.create(url=url, title=title, crawl=crawl, folder=child, config={"PERMISSIONS": visibility})
    parent.refresh_from_db()
    parent.rules = {**parent.rules, "limit": 1, "sort": "title"}
    parent.save(update_fields=["rules"])
    assert not public_snapshots_queryset(Folder.select_snapshots(Snapshot.objects.all(), parent.pk)).exists()
    response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    assert not response.context["sidebar_folder_tree"]
    response = client.get("/public/sidebar/", {"sidebar": "folders"}, HTTP_HOST=WEB_TEST_HOST)
    assert parent.name not in response.json()["html"]
    assert child.name not in response.json()["html"]
    assert [item.pk for item in Folder.tree(public=True, path_pattern=re.compile(child.name))] == [child.pk]
    selected = Snapshot.objects.get(crawl=crawl, title="A")
    selected.config = {"PERMISSIONS": "public"}
    selected.save(update_fields=["config"])
    response = client.get("/public/", {"folder": str(parent.pk)}, HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    assert {item.pk for item in response.context["sidebar_folder_tree"]} == {parent.pk, child.pk}
    assert [item.pk for item in response.context["object_list"]] == [selected.pk]
