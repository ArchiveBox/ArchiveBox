"""The temporary native crash probe cannot inherit a provider persona."""

import os
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_canva_probe_is_manual_public_and_uses_gallery_settings():
    text = (ROOT / ".github/workflows/diagnose-canva.yml").read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["diagnose"]
    assert "environment" not in job
    assert "secrets." not in text
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "20"
    steps = job["steps"]
    assert steps[0]["with"]["persist-credentials"] == "false"
    gallery = yaml.load((ROOT / ".github/workflows/screenshots.yml").read_text(), Loader=yaml.BaseLoader)
    for name in (
        "Install ArchiveBox and screenshot dependencies",
        "Install the matching Chrome sandbox helper",
        "Configure local Wayback submission service",
    ):
        assert next(s["run"] for s in steps if s["name"] == name) == next(
            s["run"] for s in gallery["jobs"]["deploy"]["steps"] if s["name"] == name
        )
    capture = next(s["run"] for s in steps if s["name"] == "Capture public Canva with native diagnostics")
    assert "env -i PATH=" in capture
    assert 'HOME="$public_root/home"' in capture
    assert "TIMEOUT=60 CHROME_HEADLESS=false CHROME_LOG_SUBPROCESS_OUTPUT=true" in capture
    assert "plugin-plan" in capture
    assert 'archivebox config --set "${enabled[@]}"' in capture
    assert "archivebox add --depth=0 --overwrite" in capture
    assert "AUTH_STORAGE_FILE" not in capture and "COOKIES_FILE" not in capture
    assert "removeUnusedFonts" not in capture
    upload = next(s for s in steps if s["name"] == "Upload public diagnostics only")
    assert upload["with"]["path"] == "${{ env.CANVA_PUBLIC_ROOT }}/diagnostics"
    for step in steps:
        if "run" in step:
            result = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
            assert result.returncode == 0, result.stderr


def test_canva_probe_resource_report_does_not_read_credentials(tmp_path):
    workflow = yaml.load((ROOT / ".github/workflows/diagnose-canva.yml").read_text(), Loader=yaml.BaseLoader)
    step = next(s for s in workflow["jobs"]["diagnose"]["steps"] if s["name"] == "Record failed capture resource diagnostics")
    sentinel = "secret-provider-sentinel-never-export"
    (tmp_path / "provider-auth.json").write_text(sentinel)
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        env={**os.environ, "CANVA_PUBLIC_ROOT": str(tmp_path), "PROVIDER_AUTH_STORAGE_JSON": sentinel},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = tmp_path / "diagnostics/system-memory.log"
    assert report.stat().st_size < 65536
    assert report.stat().st_mode & 0o077 == 0
    assert sentinel not in report.read_text() + result.stdout + result.stderr
    assert (tmp_path / "provider-auth.json").read_text() == sentinel
