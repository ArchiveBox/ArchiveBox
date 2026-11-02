"""Git cards summarize real manifests without embedding their file browser."""

import html
import subprocess

import pytest
from abx_dl.output_files import OutputManifest
from django.db.models import prefetch_related_objects
from django.template import Context, Template
from django.test import Client
from django.utils.html import escapejs

from archivebox.core.models import ArchiveResult
from archivebox.core.routes_util import get_snapshot_host
from archivebox.machine.models import Machine


@pytest.mark.django_db
@pytest.mark.parametrize("prefetched", [False, True])
def test_manifest_count_preserves_valid_paths_exclusions_and_deduplication(snapshot, prefetched):
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": "http://archivebox.localhost"}
    machine.save(update_fields=["config"])
    snapshot.url = "https://github.com/ArchiveBox/card-fixture"
    snapshot.permissions = "public"
    snapshot.status = "sealed"
    snapshot.save(update_fields=["url", "permissions", "status"])
    repo = snapshot.output_dir / "git"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    expected = {"README.md", "src/on_Snapshot__retained.txt", "src/git.jsonl"}
    expected.update(f"src/module-{i:04d}.txt" for i in range(1024))
    for name in expected:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Real archived file: {name}\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=ArchiveBox Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "Real card fixture",
        ],
        check=True,
    )
    for name in ("on_Snapshot__metadata.json", "git.jsonl", "nested/.git/private"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Capture metadata\n")
    manifest = OutputManifest.scan(repo, containment_root=snapshot.output_dir).as_mapping()
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="git",
        hook_name="git-first",
        status="succeeded",
        output_str="README.md",
        output_files=manifest,
    )
    # Another real result can report the same bytes as snapshot-root paths.
    # Invalid stored paths must never increase the visible inventory count.
    root_manifest = {f"git/{path}": {**info, "root_relative": True} for path, info in manifest.items()}
    root_manifest.update({path: {"root_relative": True} for path in ("/outside", "../outside", "git/./README.md", "git//README.md")})
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="git",
        hook_name="git-second",
        status="succeeded",
        output_str="README.md",
        output_files=root_manifest,
    )
    page = snapshot.output_dir / "dom/output.html"
    page.parent.mkdir()
    page.write_text(
        '<html><meta name="description" content="Saved repository description"><body><a class="topic-tag">archives</a></body></html>',
    )
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="dom",
        status="succeeded",
        output_str="output.html",
        output_files=OutputManifest.scan(page.parent).as_mapping(),
    )

    if prefetched:
        prefetch_related_objects([snapshot], "archiveresult_set")

    host = get_snapshot_host(str(snapshot.id))
    client = Client()
    # This core capability ships before plugin templates consume it. Exercise
    # the real template API against stored manifests independently of the
    # installed plugin version, keeping the full browser and bytes unchanged.
    rendered = Template(
        "{% load core_tags %}"
        "{% snapshot_results snapshot 'git,dom' as captures %}"
        "{% manifest_file_count captures 'git' exclude_parts='.git' "
        "exclude_prefixes='on_Snapshot__' exclude_names='git.jsonl' as count %}"
        "{{ count }} captured files",
    ).render(Context({"snapshot": snapshot}))
    assert rendered == f"{len(expected)} captured files"
    assert len(rendered) < 32
    assert (
        Template(
            "{% load core_tags %}{% snapshot_results snapshot 'git,dom' as captures %}{% manifest_file_count captures 'dom' %}",
        ).render(Context({"snapshot": snapshot}))
        == "1"
    )
    full = client.get("/git/README.md?preview=1", HTTP_HOST=host)
    assert full.status_code == 200
    assert escapejs("module-1023.txt") in html.unescape(full.content.decode())
    raw = client.get("/git/src/module-1023.txt?raw=1", HTTP_HOST=host)
    assert raw.status_code == 200
    assert b"".join(raw.streaming_content) == (repo / "src/module-1023.txt").read_bytes()
