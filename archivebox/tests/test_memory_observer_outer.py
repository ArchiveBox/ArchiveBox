"""Observe a real helper's nested database work without reading request data."""

import json
import sys
import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from archivebox.core.views import _visible_replay_snapshots_for_domain
from archivebox.workers.memory_observer import thread_activity


@pytest.mark.django_db
def test_outer_replay_remains_visible_during_real_database_work(snapshot):
    secret = "private-fixture-marker-not-for-logs"
    request = RequestFactory().get("/original/example.com/?token=" + secret)
    request.user = AnonymousUser()
    observed = []

    def profile(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "execute" and frame.f_globals.get("__name__", "").startswith("django.db."):
            observed.append(thread_activity())

    sys.setprofile(profile)
    try:
        _visible_replay_snapshots_for_domain(request, "example.com")
    finally:
        sys.setprofile(None)
    assert observed
    assert any(inner["database"] >= 1 and outer["original_replay"] >= 1 for inner, outer in observed)
    for inner, outer in observed:
        assert set(outer) == {
            "original_replay",
            "snapshot_replay",
            "static",
            "admin",
            "search",
            "opencode",
            "other",
            "unobserved",
            "depth_limited",
        }
        assert all(type(value) is int and value >= 0 for value in (*inner.values(), *outer.values()))
    serialized = json.dumps(observed)
    assert secret not in serialized and "example.com" not in serialized and "\n" not in serialized


@pytest.mark.django_db
@pytest.mark.parametrize("family", ["admin", "search", "opencode"])
def test_real_alternative_dispatch_families(admin_client, snapshot, family):
    from archivebox.core.models import Snapshot
    from archivebox.search.views import iter_meta_search_ids
    from archivebox.plugins.host import host
    from abx_plugins.plugins.opencode.archivebox.views import _dispatch
    from django.http import Http404

    observed = []

    def profile(frame, event, arg):
        if event == "call" and frame.f_code.co_name in {"execute", "_dispatch"}:
            observed.append(thread_activity()[1])

    sys.setprofile(profile)
    try:
        if family == "admin":
            response = admin_client.get("/admin/core/snapshot/")
            assert response.status_code == 200
        elif family == "search":
            list(iter_meta_search_ids("fixture", Snapshot.objects.all()))
        else:
            # Anonymous dispatch cannot start the service or touch a session.
            request = RequestFactory().get("/admin/agent/")
            request.user = AnonymousUser()
            try:
                response = _dispatch(request, host=host)
                assert response.status_code == 302
            except Http404:
                pass  # Disabled plugin is also a legitimate early dispatch.
    finally:
        sys.setprofile(None)
    assert any(counters[family] > 0 for counters in observed)
