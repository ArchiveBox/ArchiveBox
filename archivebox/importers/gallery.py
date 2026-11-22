"""Populate importer gallery views through the native CLI and full capture runner."""

import json
import subprocess
import sys
from urllib.parse import urlsplit


def importer_view_names(name):
    return (name, name + " history", name + " snapshots", name + " export")


def prepare(admin_base_url, recipes, *, on_unavailable=None):
    def command(*args):
        result = subprocess.run([sys.executable, "-m", "archivebox", *args], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout

    def runs_for(source_id):
        return json.loads(command("importer", "runs", "--source-id", source_id, "--format", "json"))

    def run_action(source_id, action):
        previous = {run["id"] for run in runs_for(source_id)}
        try:
            command("manage", "importers", "--source", source_id, "--action", action)
        except RuntimeError:
            new = [run for run in runs_for(source_id) if run["id"] not in previous]
            if on_unavailable is None or len(new) != 1 or new[0]["action"] != action or new[0]["status"] not in {"failed", "needs_login"}:
                raise
            return False
        return True

    def unavailable(recipe):
        for name in importer_view_names(recipe["name"]):
            on_unavailable(name)

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
                ),
            )
        source_id = source["id"]
        if not run_action(source_id, "preview"):
            unavailable(recipe)
            continue
        runs = runs_for(source_id)
        imports = [run for run in runs if run["action"] == "import"]
        if not imports:
            if not run_action(source_id, "import"):
                unavailable(recipe)
                continue
            runs = runs_for(source_id)
            imports = [run for run in runs if run["action"] == "import"]
        if not imports or any(run["status"] != "succeeded" for run in runs):
            raise RuntimeError("Importer gallery requires successful preview and import records.")
        if not any(run["items"] for run in imports):
            if on_unavailable is None:
                raise RuntimeError("Importer gallery requires nonempty imported records.")
            unavailable(recipe)
            continue
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
