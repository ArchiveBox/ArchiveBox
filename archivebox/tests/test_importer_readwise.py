"""Readwise registration and native import handoff with published example data."""

import json

from archivebox.tests.conftest import run_python_cwd
from archivebox.tests.test_importers import import_site  # noqa: F401


def test_readwise_importer_preserves_metadata_and_password(initialized_archive, import_site):  # noqa: F811
    from archivebox.plugins.discovery import get_plugin_catalog

    root, url = import_site
    plugin = get_plugin_catalog()["importer_readwise"]
    assert not plugin.filter_hooks("Snapshot")
    example = json.loads((plugin.path / "tests/fixtures/reader-list.json").read_text())
    example["nextPageCursor"] = None
    (root / "reader.json").write_text(json.dumps(example))
    script = """
import asyncio, json, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.core.settings")
import django
django.setup()
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils.dateparse import parse_datetime
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.importers.models import ImporterSource
from archivebox.importers.service import run_next_importer
from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.services.runner import CrawlRunner

user = get_user_model().objects.create_superuser(username="reader-test", password="readwise-test-password")
client = Client(HTTP_HOST="admin.archivebox.localhost:5797")
client.force_login(user)
catalog = client.get("/admin/importers/")
assert catalog.status_code == 200 and b"Readwise" in catalog.content
path = "/admin/importers/new/importer_readwise/documents/"
page = client.get(path)
assert page.status_code == 200 and b'type="password"' in page.content
data = {"name": "Reader", "setting_READWISE_TOKEN": "example-token", "setting_READWISE_LOCATION": "all", "setting_READWISE_API_URL": ENDPOINT}
response = client.post(path, data)
assert response.status_code == 302, response.content
source = ImporterSource.objects.get(name="Reader")
edit = client.get(f"/admin/importers/{source.pk}/edit/")
assert edit.status_code == 200 and b"example-token" not in edit.content
response = client.post(f"/admin/importers/{source.pk}/edit/", {**data, "setting_READWISE_TOKEN": ""})
assert response.status_code == 302, response.content
source.refresh_from_db()
assert source.settings["READWISE_TOKEN"] == "example-token"
assert client.post(f"/admin/importers/{source.pk}/preview/").status_code == 302
assert run_next_importer()
preview = source.runs.get()
assert preview.status == "succeeded", preview.message
assert len(preview.items) == 3 and not Crawl.objects.exists()
source.refresh_from_db()
assert source.checkpoint == {}
assert client.post(f"/admin/importers/{source.pk}/import/").status_code == 302
assert run_next_importer()
run = source.runs.get(action="import")
assert run.status == "succeeded", run.message
assert run.crawl.config["PARSER"] == "jsonl"
runner = CrawlRunner(run.crawl, show_progress=False)
try:
    runner.load_run_state()
finally:
    asyncio.run(runner.bus.destroy(clear=False))
examples = json.loads((get_plugin_catalog()["importer_readwise"].path / "tests/fixtures/reader-list.json").read_text())["results"]
assert Snapshot.objects.count() == len(examples)
for document in examples:
    snapshot = Snapshot.objects.get(url=document["source_url"])
    assert snapshot.title == document["title"], (snapshot.title, document["title"])
    assert snapshot.bookmarked_at == parse_datetime(document["saved_at"])
    assert snapshot.depth == 0
source.refresh_from_db()
assert "updated_after" in source.checkpoint
print("Readwise catalog, form, preview, import, and persisted snapshot metadata verified")
"""
    script = "ENDPOINT = " + repr(f"{url}/reader.json") + "\n" + script
    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=120)
    assert code == 0, stdout + stderr
    assert "persisted snapshot metadata verified" in stdout
