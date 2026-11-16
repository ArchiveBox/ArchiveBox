"""CI persona refreshes preserve unrelated sessions across both export formats."""

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("workflow", ["screenshots.yml", "test-parallel.yml"])
@pytest.mark.parametrize("provider_domain", ["figma.com", "canva.com"])
@pytest.mark.parametrize("base_extension", [False, True])
@pytest.mark.parametrize("refresh_extension", [False, True])
def test_workflow_persona_merge(tmp_path, workflow, provider_domain, base_extension, refresh_extension):
    path = Path(__file__).resolve().parents[2] / ".github/workflows" / workflow
    script = textwrap.dedent(path.read_text().split("<<'PYAUTH'\n", 1)[1].split("          PYAUTH", 1)[0])
    auth_file = tmp_path / "auth.json"
    unrelated_domain = "canva.com" if provider_domain == "figma.com" else "figma.com"
    secret = provider_domain.split(".")[0].upper() + "_AUTH_STORAGE_JSON"

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
        cookies=[cookie(unrelated_domain, base_extension), cookie(provider_domain, base_extension)],
        origins=[
            {"origin": f"https://{unrelated_domain}", "localStorage": [{"name": "keep", "value": "yes"}]},
            {"origin": f"https://{provider_domain}", "localStorage": []},
        ],
        tabs=[
            {"url": f"https://{unrelated_domain}/design", "sessionStorage": [{"name": "keep", "value": "yes"}]},
            {"url": f"https://{provider_domain}/design", "sessionStorage": []},
        ],
    )
    refresh = state(
        refresh_extension,
        cookies=[cookie(f"www.{provider_domain}", refresh_extension), cookie(f"{provider_domain}.attacker.example", refresh_extension)],
    )

    def merge(original, update):
        auth_file.write_text(json.dumps(original))
        result = subprocess.run(
            [sys.executable, "-", str(auth_file)],
            input=script,
            env={**os.environ, "FIGMA_AUTH_STORAGE_JSON": "", "CANVA_AUTH_STORAGE_JSON": "", secret: json.dumps(update)},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(auth_file.read_text())

    merged = merge(base, refresh)
    expected = {
        "cookies": [cookie(unrelated_domain, False), cookie(f"www.{provider_domain}", False)],
        "origins": base["origins"],
        "tabs": base["tabs"],
    }
    assert merged == expected
    assert merge(merged, state(refresh_extension)) == merged
    assert merge(merged, state(refresh_extension, cookies=[])) == {**expected, "cookies": [cookie(unrelated_domain, False)]}
    assert merge(merged, state(refresh_extension, origins=[], tabs=[])) == {
        **expected,
        "origins": base["origins"][:1],
        "tabs": base["tabs"][:1],
    }


@pytest.mark.parametrize("workflow", ["screenshots.yml", "test-parallel.yml"])
def test_workflow_persona_refreshes_are_optional_and_domain_scoped(tmp_path, workflow):
    import yaml

    path = Path(__file__).resolve().parents[2] / ".github/workflows" / workflow
    workflow_data = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    steps = [step for job in workflow_data["jobs"].values() for step in job.get("steps", [])]
    step = next(step for step in steps if step.get("name", "").startswith("Prepare authorized provider persona"))
    assert step["env"]["CANVA_AUTH_STORAGE_JSON"] == "${{ secrets.CANVA_AUTH_STORAGE_JSON }}"
    assert step["env"]["FIGMA_AUTH_STORAGE_JSON"] == "${{ secrets.FIGMA_AUTH_STORAGE_JSON }}"
    script = textwrap.dedent(path.read_text().split("<<'PYAUTH'\n", 1)[1].split("          PYAUTH", 1)[0])
    auth_file = tmp_path / "auth.json"

    def state(domain, value):
        return {
            "cookies": [{"domain": domain, "name": "session", "value": value}],
            "origins": [{"origin": f"https://{domain}", "localStorage": [{"name": "session", "value": value}]}],
            "tabs": [{"url": f"https://{domain}/design", "sessionStorage": [{"name": "session", "value": value}]}],
        }

    base = {field: [] for field in ("cookies", "origins", "tabs")}
    for domain in ("miro.com", "figma.com", "canva.com"):
        for field, items in state(domain, "old").items():
            base[field].extend(items)
    raw_base = json.dumps(base)
    for with_refresh in (False, True):
        auth_file.write_text(raw_base)
        refreshes = {}
        for provider in ("figma", "canva"):
            refresh = state(f"www.{provider}.com", "fresh")
            for field, items in state(f"{provider}.com.attacker.example", "never-import").items():
                refresh[field].extend(items)
            refreshes[f"{provider.upper()}_AUTH_STORAGE_JSON"] = json.dumps(refresh) if with_refresh else ""
        result = subprocess.run(
            [sys.executable, "-", str(auth_file)],
            input=script,
            env={**os.environ, **refreshes},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert not result.stdout and not result.stderr
        if not with_refresh:
            assert auth_file.read_text() == raw_base
            continue
        expected = {
            field: state("miro.com", "old")[field] + state("www.figma.com", "fresh")[field] + state("www.canva.com", "fresh")[field]
            for field in base
        }
        assert json.loads(auth_file.read_text()) == expected
