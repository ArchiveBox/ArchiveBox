"""Populate importer gallery views through the native CLI and full capture runner."""

import json
import subprocess
import sys
from urllib.parse import urlsplit


def prepare(admin_base_url, recipes):
    def command(*args):
        result = subprocess.run([sys.executable, "-m", "archivebox", *args], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout

    views = []
    for recipe in recipes:
        sources = json.loads(command("importer", "list", "--format", "json"))
        source = next(
            (
                source
                for source in sources
                if source["plugin"] == recipe["plugin"]
                and source["feed"] == recipe["feed"]
                and source["settings"] == recipe["settings"]
                and source["name"] == recipe["name"]
            ),
            None,
        )
        if source is None:
            source = json.loads(
                command(
                    "importer",
                    "create",
                    "--plugin",
                    recipe["plugin"],
                    "--feed",
                    recipe["feed"],
                    "--name",
                    recipe["name"],
                    "--tags",
                    "screenshot-gallery",
                    "--settings",
                    json.dumps(recipe["settings"]),
                )
            )
        source_id = source["id"]
        command("manage", "importers", "--source", source_id, "--action", "preview")
        runs = json.loads(command("importer", "runs", "--source-id", source_id, "--format", "json"))
        imports = [run for run in runs if run["action"] == "import"]
        if not imports:
            command("manage", "importers", "--source", source_id, "--action", "import")
            runs = json.loads(command("importer", "runs", "--source-id", source_id, "--format", "json"))
            imports = [run for run in runs if run["action"] == "import"]
        if not imports or any(run["status"] != "succeeded" for run in runs) or not any(run["items"] for run in imports):
            raise RuntimeError("Importer gallery requires successful preview and nonempty imported records.")
        for crawl_id in dict.fromkeys(run["crawl_id"] for run in imports if run["crawl_id"]):
            # No plugin selector: every imported URL receives the normal full capture.
            print(f"[*] Verifying full importer capture: {crawl_id}", file=sys.stderr)
            command("run", "--crawl-id", crawl_id)
        run = next(run for run in imports if run["items"])
        for name, path, mode in (
            (recipe["name"], f"/admin/importers/runs/{run['id']}/", ""),
            (recipe["name"] + " export", f"/admin/importers/runs/{run['id']}/", "view-export-menu"),
            (recipe["name"] + " history", f"/admin/importers/{source_id}/", ""),
            (recipe["name"] + " snapshots", f"/admin/core/snapshot/?crawl_id={run['crawl_id']}", ""),
        ):
            views.append("|".join((name, admin_base_url + path, urlsplit(path).path, "archivebox/importers/views.py", mode)))
    return views
