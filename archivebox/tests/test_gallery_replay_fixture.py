import io
import json
import zipfile

import pytest
from warcio.archiveiterator import ArchiveIterator

from archivebox.core.gallery_replay_fixture import prepare_folder
from archivebox.tests.conftest import ADMIN_TEST_HOST


@pytest.mark.django_db(transaction=True)
def test_gallery_replay_fixture(admin_client, tmp_path):
    from archivebox.core.exports import get_export_queryset
    from archivebox.core.models import Folder
    from archivebox.domains.exports import write_wacz_site

    fixture = prepare_folder()
    folder = Folder.objects.get(pk=fixture["folder_id"])
    snapshots = get_export_queryset({"folder": str(folder.pk)}, public_only=False)
    assert set(map(str, snapshots.values_list("crawl_id", flat=True))) == {fixture["crawl_id"]}
    assert snapshots.count() == 4
    response = admin_client.get("/admin/core/snapshot/", {"folder": str(folder.pk)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"A digital field journal" in response.content
    assert write_wacz_site(tmp_path, snapshots, title=folder.name, progress=lambda _: None) == 4

    with zipfile.ZipFile(tmp_path / "site.wacz") as bundle:
        index = json.loads(bundle.read("datapackage.json"))
        assert index["mainPageUrl"] == fixture["homepage"]
        pages = {}
        for resource in index["resources"]:
            with zipfile.ZipFile(io.BytesIO(bundle.read(resource["path"]))) as child:
                records = ArchiveIterator(io.BytesIO(child.read("archive/data.warc.gz")))
                record = next(records)
                pages[record.rec_headers.get_header("WARC-Target-URI")] = record.content_stream().read()
    assert set(pages) == {fixture["homepage"], *fixture["stories"]}
    assert all(f'href="{url}"'.encode() in pages[fixture["homepage"]] for url in fixture["stories"])


@pytest.mark.django_db(transaction=True)
def test_clone_fixture_preserves_existing_recording_and_fills_linked_page(crawl, tmp_path):
    from pathlib import Path

    from archivebox.core.gallery_replay_fixture import prepare_site_navigation
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.domains.exports import write_wacz_site

    directory = Path(__file__).parent / "fixtures/site-navigation"
    homepage = "http://127.0.0.1:8723/site-navigation/index.html"
    crawl.urls = homepage
    crawl.save(update_fields=["urls"])
    snapshot = Snapshot.objects.create(crawl=crawl, url=homepage, status=Snapshot.StatusChoices.SEALED)
    old = snapshot.output_dir / "archivewebpage/archivewebpage.wacz"
    old.parent.mkdir(parents=True)
    # A valid already saved recording is preserved across repeated fallback calls.
    from archivebox.core.gallery_replay_fixture import write_recording

    write_recording(old, homepage, "Field Notes", (directory / "index.html").read_bytes())
    old_bytes = old.read_bytes()
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="archivewebpage",
        hook_name="native",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="archivewebpage/archivewebpage.wacz",
        output_size=len(old_bytes),
        output_files={"archivewebpage/archivewebpage.wacz": {"size": len(old_bytes), "mimetype": "application/wacz"}},
    )
    for _ in range(2):
        prepare_site_navigation(crawl.pk, directory)
    assert old.read_bytes() == old_bytes
    snapshots = Snapshot.objects.filter(crawl=crawl)
    assert snapshots.count() == 2
    assert write_wacz_site(tmp_path, snapshots, title="Field Notes", progress=lambda _: None) == 2
    chapter = snapshots.get(url__endswith="/chapter.html")
    assert (chapter.output_dir / "dom/gallery-fixture/output.html").read_bytes() == (directory / "chapter.html").read_bytes()
    with zipfile.ZipFile(chapter.output_dir / "archivewebpage/gallery-fixture.wacz") as child:
        records = ArchiveIterator(io.BytesIO(child.read("archive/data.warc.gz")))
        payloads = {
            record.rec_headers.get_header("WARC-Target-URI").rsplit("/", 1)[-1]: record.content_stream().read() for record in records
        }
    assert payloads == {name: (directory / name).read_bytes() for name in ("chapter.html", "style.css", "notebook.svg")}
