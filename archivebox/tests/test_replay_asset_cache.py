"""Installed replay assets revalidate without resending unchanged worker bytes."""

import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from abx_plugins import get_plugins_dir
from django.test import Client

from archivebox.config.common import get_config
from archivebox.core.routes_util import build_snapshot_url, get_admin_host
from archivebox.machine.models import Machine
from archivebox.tests.conftest import resolve_abxpkg_binary_env


@pytest.fixture
def replay_extension(browser_runtime, hermetic_lib_dir):
    resolve_abxpkg_binary_env(browser_runtime["lib_dir"], deps_from=Path(get_plugins_dir()) / "archivewebpage/config.json")
    source = next((browser_runtime["lib_dir"] / "chromewebstore/extensions").glob("*__archivewebpage"))
    # Copy the real installed vendor so a changed-asset request cannot modify
    # another test's shared browser installation.
    target = hermetic_lib_dir / "chromewebstore/extensions" / source.name
    shutil.copytree(source, target)
    machine = Machine.current()
    machine.config = {**machine.config, "ABXPKG_LIB_DIR": str(hermetic_lib_dir), "BASE_URL": "http://archivebox.localhost:5797"}
    machine.save(update_fields=["config"])
    return target


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
@pytest.mark.parametrize("permissions", ["public", "private"])
@pytest.mark.parametrize("asset", ["sw.js", "sw-index.js", "ui.js"])
def test_replay_assets_revalidate_final_bytes_after_authorization(snapshot, admin_user, replay_extension, mode, permissions, asset):
    from abx_plugins.plugins.archivewebpage.presentation import serve_replay_asset

    machine = Machine.current()
    machine.config = {**machine.config, "SERVER_SECURITY_MODE": mode}
    machine.save(update_fields=["config"])
    snapshot.config = {**snapshot.config, "PERMISSIONS": permissions}
    snapshot.save(update_fields=["config"])
    route = urlsplit(build_snapshot_url(str(snapshot.pk), f"replay/{asset}"))
    client = Client()
    admin = Client()
    if permissions == "private":
        denied = client.get(route.path, HTTP_HOST=route.netloc, HTTP_IF_NONE_MATCH="*")
        assert denied.status_code in (302, 403, 404)
        admin.force_login(admin_user)
        grant = admin.get(
            f"/admin/core/snapshot/replay-auth/?snapshot={snapshot.pk}&next={route.path}",
            HTTP_HOST=get_admin_host(),
        )
        assert grant.status_code == 302
        target = urlsplit(grant["Location"])
        assert client.get(f"{target.path}?{target.query}", HTTP_HOST=target.netloc).status_code == 302

    response = client.get(route.path, HTTP_HOST=route.netloc)
    assert response.status_code == 200
    assert len(response.content) > 100_000
    etag = f'"{hashlib.sha256(response.content).hexdigest()}"'
    assert response["ETag"] == etag
    if asset != "ui.js":
        original, _type, _headers = serve_replay_asset(f"replay/{asset}", get_config())
        assert hashlib.sha256(original).hexdigest() != hashlib.sha256(response.content).hexdigest()
        assert response["Service-Worker-Allowed"] == "/"
        assert "no-cache" in response["Cache-Control"]
    head = client.head(route.path, HTTP_HOST=route.netloc)
    assert head.status_code == 200 and head.content == b""
    assert head["Content-Length"] == str(len(response.content))
    assert head["ETag"] == etag

    for method in (client.get, client.head):
        cached = method(route.path, HTTP_HOST=route.netloc, HTTP_IF_NONE_MATCH=etag)
        assert cached.status_code == 304
        assert cached.content == b""
        for header in ("ETag", "Cache-Control", "Vary", "Service-Worker-Allowed", "X-Content-Type-Options", "Content-Security-Policy"):
            assert cached.get(header) == response.get(header), header

    if asset == "ui.js":
        # The host adds snapshot-specific metadata to the HTML fallback after
        # the plugin responds, so it must not expose the plugin's byte validator.
        html = client.get(route.path.rsplit("/", 1)[0] + "/replay.html", HTTP_HOST=route.netloc, HTTP_IF_NONE_MATCH="*")
        assert html.status_code == 200
        assert "ETag" not in html
        assert b"<replay-app-main>" in html.content
        with (replay_extension / "ui.js").open("ab") as source:
            source.write(b"\n// Updated installed replay UI.\n")
        changed = client.get(route.path, HTTP_HOST=route.netloc, HTTP_IF_NONE_MATCH=etag)
        assert changed.status_code == 200
        assert changed.content.endswith(b"// Updated installed replay UI.\n")
        assert changed["ETag"] == f'"{hashlib.sha256(changed.content).hexdigest()}"'
        assert changed["ETag"] != etag

    if permissions == "private":
        admin.logout()
        revoked = client.get(route.path, HTTP_HOST=route.netloc, HTTP_IF_NONE_MATCH=etag)
        assert revoked.status_code in (302, 403, 404)
