import json

import pytest

from archivebox.config.common import ArchiveBoxConfig
from archivebox.misc.util import download_url


def test_default_user_agent_is_automatic():
    assert ArchiveBoxConfig().USER_AGENT == ""


@pytest.mark.parametrize("override", ["", "Explicit capture identity"])
def test_import_download_uses_shared_browser_identity(tmp_path, httpserver, override):
    # The native Chrome lifecycle owns this cache; import requests only read it.
    recorded_user_agent = "Recorded native browser identity"
    (tmp_path / "chrome-user-agent.json").write_text(json.dumps({"userAgent": recorded_user_agent}))
    expected = override or recorded_user_agent
    httpserver.expect_request("/bookmarks", headers={"User-Agent": expected}).respond_with_data("saved bookmark input")
    config = ArchiveBoxConfig(USER_AGENT=override, ABXPKG_LIB_DIR=tmp_path)
    assert download_url(httpserver.url_for("/bookmarks"), config=config) == "saved bookmark input"
    httpserver.check_assertions()
