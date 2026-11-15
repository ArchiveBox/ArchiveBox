"""CI persona refreshes preserve unrelated sessions across both export formats."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("workflow", ["screenshots.yml", "test-parallel.yml"])
@pytest.mark.parametrize("base_extension", [False, True])
@pytest.mark.parametrize("refresh_extension", [False, True])
def test_workflow_persona_merge(tmp_path, workflow, base_extension, refresh_extension):
    path = Path(__file__).resolve().parents[2] / ".github/workflows" / workflow
    script = textwrap.dedent(path.read_text().split("<<'PYAUTH'\n", 1)[1].split("          PYAUTH", 1)[0])
    auth_file = tmp_path / "auth.json"

    def cookie(domain, extension):
        return {
            "domain": domain,
            "name": "session",
            "value": domain,
            "path": "/",
            "secure": True,
            "httpOnly": True,
            "sameSite": "no_restriction" if extension else "None",
            "expirationDate" if extension else "expires": 2000000000,
        }

    def state(extension, **fields):
        return {**({"SOURCE": "archivebox-browser-extension"} if extension else {}), **fields}

    base = state(
        base_extension,
        cookies=[cookie("canva.com", base_extension), cookie("figma.com", base_extension)],
        origins=[
            {"origin": "https://canva.com", "localStorage": [{"name": "keep", "value": "yes"}]},
            {"origin": "https://figma.com", "localStorage": []},
        ],
        tabs=[
            {"url": "https://canva.com/design", "sessionStorage": [{"name": "keep", "value": "yes"}]},
            {"url": "https://figma.com/design", "sessionStorage": []},
        ],
    )
    refresh = state(
        refresh_extension,
        cookies=[cookie("www.figma.com", refresh_extension), cookie("figma.com.attacker.example", refresh_extension)],
    )

    def merge(original, update):
        auth_file.write_text(json.dumps(original))
        result = subprocess.run(
            [sys.executable, "-", str(auth_file)],
            input=script,
            env={**os.environ, "FIGMA_AUTH_STORAGE_JSON": json.dumps(update)},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(auth_file.read_text())

    merged = merge(base, refresh)
    expected = {
        "cookies": [cookie("canva.com", False), cookie("www.figma.com", False)],
        "origins": base["origins"],
        "tabs": base["tabs"],
    }
    assert merged == expected
    assert merge(merged, state(refresh_extension)) == merged
    assert merge(merged, state(refresh_extension, cookies=[])) == {**expected, "cookies": [cookie("canva.com", False)]}
    assert merge(merged, state(refresh_extension, origins=[], tabs=[])) == {
        **expected,
        "origins": base["origins"][:1],
        "tabs": base["tabs"][:1],
    }
