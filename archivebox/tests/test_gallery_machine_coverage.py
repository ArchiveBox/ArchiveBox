"""The full gallery requires the canonical machine settings view in every viewport."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "bin/generate_ui_screenshot_gallery.py"


@pytest.mark.parametrize("missing_profile", [None, "all", "desktop", "tablet", "mobile"])
def test_gallery_requires_canonical_machine_settings(tmp_path, missing_profile):
    generator = runpy.run_path(str(GENERATOR))
    # Model the collector's current names independently of the validator's set.
    names = (generator["REQUIRED_VIEW_NAMES"] - {"Machine detail", "System settings"}) | {"Machine settings"}
    names.update(generator["plugin_screenshot_plan"]()["required"])
    png = (ROOT / "archivebox/tests/fixtures/redirected-image/image.png").read_bytes()
    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    captures = []
    for number, name in enumerate(sorted(names)):
        for profile, (width, height) in generator["CAPTURE_PROFILES"].items():
            if name == "Machine settings" and missing_profile in {"all", profile}:
                continue
            filename = f"{number}-{profile}.png"
            (screenshots / filename).write_bytes(png)
            captures.append(
                {
                    "name": name,
                    "url": "http://admin.archivebox.localhost/admin/machine/machine/fixture/change/",
                    "source": "archivebox/machine/admin.py",
                    "filename": filename,
                    "profile": profile,
                    "width": width,
                    "height": height,
                },
            )
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(capture) + "\n" for capture in captures))
    env = {**os.environ, "GITHUB_SHA": "fd8c983f5005128df06c994ed7ad7f2bbc3a2d1a"}
    env.pop("UI_SCREENSHOT_ALLOW_PARTIAL", None)
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "build", str(manifest), str(tmp_path / "UI.md"), str(screenshots / "index.html")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if missing_profile is None:
        assert result.returncode == 0, result.stderr
        assert "Machine settings" in (screenshots / "index.html").read_text()
        assert json.loads((screenshots / "build.json").read_text())["capture_count"] == len(captures)
    else:
        assert result.returncode != 0
        expected = (
            "required UI screenshot coverage is missing: Machine settings"
            if missing_profile == "all"
            else f"missing {missing_profile} capture for Machine settings"
        )
        assert expected in result.stderr
        assert not (screenshots / "build.json").exists()


def test_collector_uses_canonical_machine_settings():
    collector = (ROOT / "bin/collect_ui_screenshots.sh").read_text()
    assert '"Machine settings|$ADMIN_BASE_URL/admin/machine/machine/$MACHINE_ID/change/|' in collector
    assert '"Machine detail|' not in collector
    assert '"System settings|' not in collector
