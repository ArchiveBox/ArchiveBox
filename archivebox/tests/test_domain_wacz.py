"""Site export preserves real recorded WACZs and their random-access layout."""

import hashlib
import json
import struct
import zipfile
from pathlib import Path

import pytest

from archivebox.domains.wacz import write_site_wacz


def test_site_wacz_preserves_recordings_and_replay_offsets(tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    sources = [fixtures / "memento/iframetest.wacz", fixtures / "responsive-images/google-drive.wacz"]
    before = [path.read_bytes() for path in sources]
    output = tmp_path / "site.wacz"
    progress = []
    with output.open("wb") as stream:
        assert write_site_wacz(stream, sources, title="Saved pages", main_url="https://example.com/", progress=progress.append) == 2
    assert progress[0]["bytes"] == 0
    assert progress[-1] == {"bytes": sum(map(len, before)), "total_bytes": sum(map(len, before)), "recordings": 2, "total_recordings": 2}
    with zipfile.ZipFile(output) as bundle, output.open("rb") as stream:
        package_bytes = bundle.read("datapackage.json")
        package = json.loads(package_bytes)
        assert package["profile"] == "multi-wacz-package"
        assert package["mainPageUrl"] == "https://example.com/"
        assert len(package["resources"]) == 2
        for resource, original in zip(package["resources"], before, strict=True):
            member = bundle.getinfo(resource["path"])
            assert member.compress_type == zipfile.ZIP_STORED
            assert bundle.read(member) == original
            assert resource["bytes"] == len(original)
            assert resource["hash"] == f"sha256:{hashlib.sha256(original).hexdigest()}"
            # wabac optimizes the member offset when the central-directory
            # extra field is empty. Its calculation must reach the ZIP bytes.
            stream.seek(member.header_offset)
            header = stream.read(30)
            name_length, extra_length = struct.unpack_from("<HH", header, 26)
            assert bool(member.extra) == bool(extra_length)
            stream.seek(member.header_offset + 30 + name_length + extra_length)
            assert stream.read(4) == b"PK\x03\x04"
        assert json.loads(bundle.read("datapackage-digest.json"))["hash"] == f"sha256:{hashlib.sha256(package_bytes).hexdigest()}"
    assert [path.read_bytes() for path in sources] == before


def test_site_wacz_requires_existing_recordings(tmp_path):
    output = tmp_path / "site.wacz"
    with output.open("wb") as stream, pytest.raises(ValueError, match="No WACZ recordings"):
        write_site_wacz(stream, [], title="Empty crawl", main_url="https://example.com/")
    assert output.stat().st_size == 0


@pytest.mark.django_db(transaction=True)
def test_exported_replay_assets_use_installed_plugin(cached_abxpkg_lib_dir):
    from archivebox.config.common import get_config
    from archivebox.domains.wacz import replay_assets
    from archivebox.plugins.discovery import get_plugin_catalog
    from archivebox.tests.conftest import install_real_binary

    plugin = get_plugin_catalog()["archivewebpage"]
    requirement = json.loads((plugin.path / "config.json").read_text())["required_binaries"][0]
    install_real_binary(requirement["name"], binproviders=requirement["binproviders"], overrides=requirement["overrides"])
    config = get_config(overrides={"ABXPKG_LIB_DIR": str(cached_abxpkg_lib_dir)})
    assets = replay_assets(config)
    extension = next((cached_abxpkg_lib_dir / "chromewebstore/extensions").glob("*__archivewebpage"))
    assert assets["replay/ui.js"] == (extension / "ui.js").read_bytes()
    assert len(assets["replay/sw.js"]) > 1000
    assert b"<html" in assets["replay/replay.html"].lower()
