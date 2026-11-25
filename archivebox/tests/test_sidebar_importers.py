"""The snapshot sidebar reuses the native importer catalog and access rules."""

from urllib.parse import urldefrag

import pytest
from django.urls import resolve, reverse

from archivebox.core.sidebar_importers import importer_add_actions, importer_entries_page, importer_sidebar_allowed
from archivebox.importers.catalog import get_importer_providers, get_importers
from archivebox.importers.models import ImporterSource
from archivebox.tests.conftest import ADMIN_TEST_HOST


@pytest.fixture
def request_for(rf, admin_user):
    def request(**params):
        req = rf.get("/", params)
        req.user = admin_user
        return req

    return request


@pytest.fixture
def providers():
    return sorted(get_importer_providers(get_importers()), key=lambda provider: provider["name"].casefold())


def _create(user, provider, name, **extra):
    definition = provider["definition"]
    return ImporterSource.objects.create(created_by=user, plugin=definition.plugin, feed=definition.feed, name=name, **extra)


@pytest.mark.django_db
def test_catalog_families_include_empty_groups_without_reading_sources(request_for, providers, django_assert_num_queries):
    first, second = providers[:2]
    req = request_for()
    with django_assert_num_queries(0):
        rows, cursor = importer_entries_page(req, term="", parent="", cursor=None, limit=1)
        second_rows, _ = importer_entries_page(req, term="", parent="", cursor=cursor, limit=1)
    assert [row["name"] for row in rows] == [first["name"]]
    assert [row["name"] for row in second_rows] == [second["name"]]
    assert rows[0]["has_children"] and rows[0]["scope"] == ""
    representative = first["definition"]
    if representative.icon:
        assert rows[0]["icon_url"] == reverse("importers:icon", args=(representative.plugin, representative.feed))
    with django_assert_num_queries(1):
        assert importer_entries_page(req, term="", parent=rows[0]["id"], cursor=None, limit=1) == ([], None)


@pytest.mark.django_db
def test_family_add_links_open_the_correct_importer_options(request_for, providers, admin_client):
    rows, _ = importer_entries_page(request_for(), term="", parent="", cursor=None, limit=len(providers))
    assert len(rows) == len(providers)
    index_url = reverse("importers:index")
    index = admin_client.get(index_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert index.status_code == 200

    for row, provider in zip(rows, providers, strict=True):
        [action] = row["actions"]
        assert action["label"] == "Add importer"
        [feed, *others] = provider["feeds"]
        if not others:
            match = resolve(action["url"])
            assert match.view_name == "importers:new"
            assert match.kwargs == {"plugin": feed.plugin, "feed": feed.feed}
        else:
            path, fragment = urldefrag(action["url"])
            assert path == index_url
            card = index.content.split(f'id="{fragment}">'.encode())[1].split(b"</article>", 1)[0]
            for option in provider["feeds"]:
                assert reverse("importers:new", args=(option.plugin, option.feed)).encode() in card


@pytest.mark.django_db
def test_importer_siblings_have_stable_bounded_name_id_pages(request_for, admin_user, providers, django_assert_num_queries):
    provider = providers[0]
    sources = [
        _create(admin_user, provider, name, settings={"private": "not an entry"})
        for name in ("same Name", "SAME NAME", "Same name", "alpha", "Zebra")
    ]
    _create(admin_user, provider, "Before everything", enabled=False)
    req = request_for()
    families, _ = importer_entries_page(req, term="", parent="", cursor=None, limit=10)
    parent = families[0]["id"]

    with django_assert_num_queries(1) as queries:
        first, cursor = importer_entries_page(req, term="", parent=parent, cursor=None, limit=2)
    sql = queries.captured_queries[0]["sql"].lower()
    assert all(column not in sql for column in ("settings", "checkpoint", "account", "importerrun"))
    with django_assert_num_queries(1):
        second, end = importer_entries_page(req, term="", parent=parent, cursor=cursor, limit=3)
    assert end is None
    assert [row["id"] for row in first + second] == [
        str(source.pk) for source in sorted(sources, key=lambda item: (item.name.casefold(), item.pk))
    ]
    for row in first + second:
        assert row["parent_id"] == parent and row["scope"] == "importer" and row["filter_value"] == row["id"]
        assert [resolve(action["url"]).view_name for action in row["actions"]] == ["importers:detail", "importers:edit"]


@pytest.mark.django_db
def test_importer_search_and_offpage_selection_reveal_bounded_ancestors(
    request_for,
    admin_user,
    providers,
    django_assert_num_queries,
):
    first, second = providers[:2]
    _create(admin_user, first, "Needle Zebra")
    a = _create(admin_user, second, "Needle A")
    b = _create(admin_user, second, "Needle B")
    _create(admin_user, second, "Needle C paused", enabled=False)
    req = request_for(importer=str(b.pk))

    with django_assert_num_queries(1):
        rows, root_cursor = importer_entries_page(req, term="", parent="", cursor=None, limit=1)
    assert [row["name"] for row in rows] == [first["name"], second["name"], b.name]
    assert rows[1]["expand"] and rows[2]["parent_id"] == rows[1]["id"]
    assert root_cursor == [rows[0]["id"]]
    with django_assert_num_queries(1):
        rows, search_cursor = importer_entries_page(req, term="needle", parent="", cursor=None, limit=1)
    # The first alphabetical family stays first, even though its only matching
    # source sorts after the children from a later family.
    assert [row["name"] for row in rows] == [first["name"], "Needle Zebra"]
    with django_assert_num_queries(1):
        rows, search_cursor = importer_entries_page(req, term="needle", parent="", cursor=search_cursor, limit=1)
    assert [row["name"] for row in rows] == [second["name"], a.name]
    assert rows[0]["expand"] and rows[1]["parent_id"] == rows[0]["id"]
    rows, search_end = importer_entries_page(req, term="needle", parent="", cursor=search_cursor, limit=1)
    assert [row["name"] for row in rows] == [second["name"], b.name]
    assert search_end is None


@pytest.mark.django_db
def test_catalog_add_options_and_non_superuser_privacy(request_for, providers, django_assert_num_queries, monkeypatch):
    from unittest.mock import Mock

    from django.contrib.auth.models import AnonymousUser

    catalog_read = Mock(wraps=get_importers)
    monkeypatch.setattr("archivebox.core.sidebar_importers.get_importers", catalog_read)
    req = request_for()
    with django_assert_num_queries(0):
        actions = importer_add_actions(req)
        importer_entries_page(req, term="", parent="", cursor=None, limit=10)
    catalog_read.assert_called_once_with()
    assert [(action["family"], action["label"], action["url"]) for action in actions] == [
        (provider["name"], feed.title, reverse("importers:new", args=(feed.plugin, feed.feed)))
        for provider in providers
        for feed in sorted(provider["feeds"], key=lambda feed: (feed.title.casefold(), feed.plugin, feed.feed))
    ]
    for property_name, user in (("", AnonymousUser()), ("is_superuser", req.user), ("is_active", req.user)):
        if property_name:
            setattr(user, property_name, False)
        req.user = user
        with django_assert_num_queries(0):
            assert not importer_sidebar_allowed(req)
            assert importer_add_actions(req) == []
            assert importer_entries_page(req, term="anything", parent="", cursor=None, limit=1) == ([], None)
        if property_name:
            setattr(user, property_name, True)
