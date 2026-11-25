"""Derived snapshot cards use the native card stack without representing saved files."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.utils.html import format_html
from lxml.html import fromstring

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.plugins.discovery import get_plugin_apps
from archivebox.plugins.host import host
from archivebox.tests.conftest import WEB_TEST_HOST


pytestmark = pytest.mark.django_db


def _snapshot(crawl, host_name, *, parent=None, permissions="public"):
    return Snapshot.objects.create(
        crawl=crawl,
        parent_snapshot=parent,
        url=f"https://{host_name}/",
        config={"PERMISSIONS": permissions},
    )


def test_plugin_owned_derived_card_is_not_a_saved_output(admin_user, monkeypatch):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://source.example/")
    snapshot = _snapshot(crawl, "source.example")

    def derived_card(adapter, request, *, snapshot_id):
        relationship = adapter.snapshot_relationships(request, snapshot_id=snapshot_id)
        assert relationship["root"]["id"] == str(snapshot.pk)
        return {
            "title": "Plugin view",
            "path": f"/admin/plugin-view/?snapshot={snapshot_id}",
            "output_group": "metadata",
            "thumbnail": format_html("<span>{}</span>", "Installed viewer thumbnail"),
        }

    installed_apps = get_plugin_apps()
    monkeypatch.setattr(
        "archivebox.plugins.discovery.get_plugin_apps",
        lambda: {**installed_apps, "test_viewer": SimpleNamespace(snapshot_detail_card=derived_card)},
    )
    response = Client().get(snapshot.get_absolute_url(), HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    card = fromstring(response.content).xpath('//div[@data-plugin-name="test_viewer"]')
    assert len(card) == 1
    assert card[0].get("data-output-group") == "metadata"
    assert not card[0].get("data-output-path")
    assert not card[0].get("data-preview-url")
    assert not card[0].xpath(".//iframe | .//*[@download] | .//button")
    assert "".join(card[0].xpath(".//h4/text()")).strip() == "Plugin view"
    assert card[0].xpath(".//a/@target") == ["_blank", "_blank"]
    assert all(path.endswith(f"/admin/plugin-view/?snapshot={snapshot.pk}") for path in card[0].xpath(".//a/@href"))
    assert "Installed viewer thumbnail" in card[0].text_content()
    assert not snapshot.archiveresult_set.exists()
    assert snapshot.get_html_details_context()["derived_snapshot_cards"] == ()


def test_snapshot_relationships_are_bounded_and_do_not_trust_presentation_cookie(rf, admin_user, django_assert_num_queries):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://source.example/")
    parent = _snapshot(crawl, "private-parent.example", permissions="private")
    snapshot = _snapshot(crawl, "source.example", parent=parent)
    _snapshot(crawl, "private-child.example", parent=snapshot, permissions="private")
    child = _snapshot(crawl, "visible-child.example", parent=snapshot)
    _snapshot(crawl, "unlisted-child.example", parent=snapshot, permissions="unlisted")

    request = rf.get("/", HTTP_COOKIE="archivebox_admin_logged_in=1")
    request.user = AnonymousUser()
    with django_assert_num_queries(3) as captured:
        visible = host.snapshot_relationships(request, snapshot_id=snapshot.pk, limit=1)
    assert visible["parent"] is None
    assert [row["id"] for row in visible["children"]] == [str(child.pk)]
    assert "LIMIT 1" in captured.captured_queries[-1]["sql"]
    with pytest.raises(PermissionDenied):
        host.snapshot_neighborhood_records(request, ids=[str(snapshot.pk)])
    request.user = admin_user
    assert host.snapshot_relationships(request, snapshot_id=snapshot.pk)["parent"] is None
    assert host.snapshot_relationships(request, snapshot_id=parent.pk)["root"]["id"] == str(parent.pk)


def test_neighborhood_resolves_exact_capture_urls_and_discovered_parents(rf, admin_user, monkeypatch):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://source.example/")
    parent = _snapshot(crawl, "first-parent.example", permissions="private")
    other = _snapshot(crawl, "other-parent.example")
    selected = _snapshot(crawl, "source.example", parent=parent)
    later_crawl = Crawl.objects.create(created_by=admin_user, urls="https://source.example/")
    latest = _snapshot(later_crawl, "source.example", parent=other)
    child = _snapshot(crawl, "child.example", parent=selected)

    request = rf.get("/")
    request.user = admin_user
    from unittest.mock import Mock

    saved_outputs = Mock(side_effect=lambda directories: (directories[0], []))
    monkeypatch.setattr(host, "_saved_url_outputs", saved_outputs)
    selected_record, latest_record = host.snapshot_neighborhood_records(request, ids=[str(selected.pk)], urls=[selected.url])
    assert [selected_record["id"], latest_record["id"]] == [str(selected.pk), str(latest.pk)]
    assert selected_record["parent_id"] == str(parent.pk)
    assert selected_record["parents"] == [{"id": str(parent.pk), "url": parent.url}, {"id": str(other.pk), "url": other.url}]
    assert selected_record["children"] == [{"id": str(child.pk), "url": child.url}]
    saved_outputs.assert_not_called()
    assert selected_record["saved_url_outputs"]()[1] == []
    saved_outputs.assert_called_once()
