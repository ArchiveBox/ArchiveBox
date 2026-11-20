import hashlib
import json
import sys
from pathlib import Path

import pytest
from werkzeug.wrappers import Response

from archivebox.config.common import ArchiveBoxConfig
from archivebox.misc.util import download_url


def test_default_user_agent_is_automatic():
    assert ArchiveBoxConfig().USER_AGENT == ""


@pytest.mark.parametrize(
    ("override", "headless", "remote", "expected"),
    [
        ("", True, False, "Recorded native browser identity"),
        ("Explicit capture identity", True, False, "Explicit capture identity"),
        ("", False, False, None),
        ("", True, True, None),
    ],
)
def test_import_download_uses_shared_browser_identity(tmp_path, httpserver, override, headless, remote, expected):
    # The native Chrome lifecycle owns this cache; imports never start a browser.
    # Use an existing executable only as an identity-key input, not as Chrome.
    executable = str(Path(sys.executable).resolve())
    args, extra = ["--lang=en"], ["--disable-extensions"]
    key = hashlib.sha256(json.dumps([executable, True, args, extra], separators=(",", ":")).encode()).hexdigest()
    (tmp_path / f"chrome-user-agent-{key}.json").write_text(json.dumps({"userAgent": "Recorded native browser identity"}))
    (tmp_path / "chrome-user-agent.json").write_text(json.dumps({"userAgent": "Unscoped old browser identity"}))
    received = []

    def serve_bookmarks(request):
        received.append(request.headers.get("User-Agent"))
        return Response("saved bookmark input")

    httpserver.expect_request("/bookmarks").respond_with_handler(serve_bookmarks)
    config = ArchiveBoxConfig(
        USER_AGENT=override,
        ABXPKG_LIB_DIR=tmp_path,
        CHROME_BINARY=executable,
        CHROME_HEADLESS=headless,
        CHROME_IS_LOCAL=not remote,
        CHROME_ARGS=args,
        CHROME_ARGS_EXTRA=extra,
    )
    assert download_url(httpserver.url_for("/bookmarks"), config=config) == "saved bookmark input"
    httpserver.check_assertions()
    assert len(received) == 1
    if expected is None:
        assert received[0] not in {"Recorded native browser identity", "Unscoped old browser identity"}
    else:
        assert received == [expected]
