"""Replay Storage keeps working when archived pages harden Object.prototype."""

import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.django_db(transaction=True)
def test_replay_storage_survives_removed_proto_accessor(snapshot, live_server, browser_runtime):
    from abx_plugins import get_plugins_dir
    from abx_plugins.plugins.base.testing import install_required_binary_from_config
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    install_required_binary_from_config(Path(get_plugins_dir()) / "archivewebpage", "archivewebpage", env=dict(os.environ))
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    output = snapshot.output_dir / "archivewebpage/google-drive.wacz"
    output.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parent / "fixtures/responsive-images/google-drive.wacz", output)
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], f"--host-resolver-rules=MAP {host} 127.0.0.1"],
        )
        page = browser.new_page()
        page.goto(f"http://{host}:{port}/archivewebpage/google-drive.wacz?preview=1", wait_until="domcontentloaded")
        page.wait_for_function("window.archiveboxReplayReady")
        frame = next(frame for frame in page.frames if "/https://drive.google.com/drive/folders/" in frame.url)
        # Removing this legacy accessor is standards-compliant page hardening;
        # it must not remove the replayer's real Storage methods or saved data.
        result = frame.evaluate("""() => {
            for (const storage of [localStorage, sessionStorage]) {
                storage.clear();
                storage.setItem('before', 'saved');
            }
            Reflect.deleteProperty(Object.prototype, '__proto__');
            Object.seal(Object.prototype);
            return [localStorage, sessionStorage].map(storage => {
                const before = storage.getItem('before');
                storage.setItem('after', 'new');
                storage.direct = 'property';
                const values = [before, storage.getItem('after'), storage.direct, storage.length, storage.key(0)];
                storage.removeItem('before');
                values.push(storage.getItem('before'), storage.length);
                storage.clear();
                values.push(storage.length);
                return values;
            });
        }""")
        assert result == [["saved", "new", "property", 3, "before", None, 2, 0]] * 2
        browser.close()
