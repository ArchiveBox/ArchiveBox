"""Build genuine scratch WACZs from the same controlled pages used for app UI checks."""

import hashlib
import io
import json
from pathlib import Path
import uuid
import zipfile
from urllib.parse import urljoin, urlsplit

from warcio.statusandheaders import StatusAndHeaders
from warcio.warcwriter import WARCWriter

STAMP = "2026-01-01T00:00:00Z"


def jsonb(data):
    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode()


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_recording(path, url, title, source, *, assets=()):
    stream = io.BytesIO()
    writer = WARCWriter(stream, gzip=True)
    index = []
    for target, mime, payload in ((url, "text/html; charset=utf-8", source), *assets):
        offset = stream.tell()
        record = writer.create_warc_record(
            target,
            "response",
            payload=io.BytesIO(payload),
            length=len(payload),
            http_headers=StatusAndHeaders("200 OK", [("Content-Type", mime)], protocol="HTTP/1.1"),
            warc_headers_dict={"WARC-Date": STAMP, "WARC-Record-ID": f"<urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, target)}>"},
        )
        writer.write_record(record)
        parsed = urlsplit(target)
        surt = ",".join(reversed((parsed.hostname or "").split(".")))
        if parsed.port:
            surt += f":{parsed.port}"
        surt += ")" + (parsed.path or "/")
        index.append(
            f"{surt} 20260101000000 ".encode()
            + jsonb(
                {
                    "url": target,
                    "digest": record.rec_headers.get_header("WARC-Payload-Digest"),
                    "mime": mime.split(";", 1)[0],
                    "status": 200,
                    "offset": offset,
                    "length": stream.tell() - offset,
                    "filename": "data.warc.gz",
                },
            )
            + b"\n",
        )
    warc = stream.getvalue()
    cdx = b"".join(sorted(index))
    pages = jsonb({"format": "json-pages-1.0", "id": "pages", "title": "All Pages"}) + b"\n"
    pages += (
        jsonb(
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, url)),
                "url": url,
                "title": title,
                "ts": STAMP,
            },
        )
        + b"\n"
    )
    members = {
        "archive/data.warc.gz": warc,
        "indexes/index.cdx": cdx,
        "pages/pages.jsonl": pages,
    }
    metadata = jsonb(
        {
            "profile": "data-package",
            "wacz_version": "1.1.1",
            "mainPageUrl": url,
            "mainPageDate": STAMP,
            "resources": [
                {
                    "name": p.rsplit("/", 1)[-1],
                    "path": p,
                    "bytes": len(b),
                    "hash": digest(b),
                }
                for p, b in members.items()
            ],
        },
    )
    members["datapackage.json"] = metadata
    members["datapackage-digest.json"] = jsonb(
        {"path": "datapackage.json", "hash": digest(metadata)},
    )
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in members.items():
            archive.writestr(zipfile.ZipInfo(name), body)


def prepare():
    """Create a gallery-only crawl, separate from native capture evidence."""
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl

    homepage = "https://field-notes.example/"
    stories = {
        "https://design-notes.example/field-journal": (
            "A digital field journal",
            "A short guide to keeping field notes, recording context, and revisiting the source material later.",
        ),
        "https://garden-notes.example/pollinators": (
            "A guide to urban pollinators",
            "A field guide to noticing insects, keeping seasonal records, and identifying plants that provide food and cover.",
        ),
        "https://map-notes.example/walking-routes": (
            "Mapping neighborhood walks",
            "How a walking map can capture landmarks, everyday shortcuts, and the details that disappear from larger maps.",
        ),
    }
    pages = {
        homepage: (
            "Field Notes",
            "<ul>" + "".join(f'<li><a href="{url}">{title}</a></li>' for url, (title, _) in stories.items()) + "</ul>",
        ),
        **{url: (title, f"<p>{body}</p>") for url, (title, body) in stories.items()},
    }
    crawl = Crawl.objects.create(
        urls="\n".join(pages),
        tags_str="screenshot-library",
        status=Crawl.StatusChoices.SEALED,
    )
    for url, (title, body) in pages.items():
        html = f"<!doctype html><html lang=en><meta charset=utf-8><title>{title}</title><main><article><h1>{title}</h1>{body}</article></main></html>".encode()
        snapshot = Snapshot.objects.create(
            url=url,
            title=title,
            crawl=crawl,
            config={"PERMISSIONS": "public"},
            status=Snapshot.StatusChoices.SEALED,
        )
        paths = {
            "dom": "dom/output.html",
            "archivewebpage": "archivewebpage/archivewebpage.wacz",
        }
        for plugin, relative in paths.items():
            output = snapshot.output_dir / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            if plugin == "dom":
                output.write_bytes(html)
                mime = "text/html"
            else:
                write_recording(output, url, title, html)
                mime = "application/wacz"
            size = output.stat().st_size
            # Model the app's usual saved-output contract. This row describes a
            # generated fixture, not an extractor that was invoked and passed.
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin=plugin,
                hook_name="gallery_fixture",
                status=ArchiveResult.StatusChoices.SUCCEEDED,
                output_str=relative,
                output_size=size,
                output_files={relative: {"size": size, "mimetype": mime}},
            )
        Snapshot.objects.filter(pk=snapshot.pk).update(
            output_size=sum((snapshot.output_dir / name).stat().st_size for name in paths.values()),
        )
    return {
        "crawl_id": str(crawl.pk),
        "homepage": homepage,
        "stories": list(stories),
        "replay_urls": {url: url for url in pages},
        "homepage_selector": "main article",
        "title": "Field Notes",
    }


def prepare_site_navigation(crawl_id, site_directory):
    """Fill missing capture roles for the disposable, app-owned local site."""
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.plugins.discovery import get_snapshot_role_paths

    directory = Path(site_directory)
    crawl = Crawl.objects.get(pk=crawl_id)
    homepage = crawl.urls.splitlines()[0]
    origin = urlsplit(homepage)
    if origin.scheme != "http" or origin.hostname not in {"127.0.0.1", "localhost"} or origin.path != "/site-navigation/index.html":
        raise ValueError("Expected the disposable gallery site-navigation crawl.")
    assets = tuple(
        (name, mime, (directory / name).read_bytes()) for name, mime in (("style.css", "text/css"), ("notebook.svg", "image/svg+xml"))
    )
    for filename, title in (("index.html", "Field Notes"), ("chapter.html", "A Walk by the River")):
        url = urljoin(homepage, filename)
        html = (directory / filename).read_bytes()
        snapshot, _ = Snapshot.objects.get_or_create(
            crawl=crawl,
            url=url,
            defaults={"title": title, "status": Snapshot.StatusChoices.SEALED},
        )
        if snapshot.status != Snapshot.StatusChoices.SEALED:
            raise ValueError("Wait for the gallery crawl to finish before preparing replay fixtures.")
        results = list(snapshot.archiveresult_set.filter(status=ArchiveResult.StatusChoices.SUCCEEDED))
        if not any((snapshot.output_dir / relative).is_file() for relative in get_snapshot_role_paths(snapshot, results, "html_replay")):
            relatives = {"dom/gallery-fixture/output.html": ("text/html", html)}
            relatives.update({f"dom/gallery-fixture/{name}": (mime, data) for name, mime, data in assets})
            for relative, (_, data) in relatives.items():
                output = snapshot.output_dir / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists():
                    # Keep the bytes left by the failed native hook available for diagnosis.
                    raise ValueError(f"Refusing to replace existing {relative} in the gallery fixture.")
                output.write_bytes(data)
            _save_gallery_output(snapshot, "dom", "dom/gallery-fixture/output.html", relatives)
        if not any(
            (relative := result.embed_path_db()) and relative.endswith(".wacz") and (snapshot.output_dir / relative).is_file()
            for result in results
        ):
            relative = "archivewebpage/gallery-fixture.wacz"
            output = snapshot.output_dir / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            write_recording(output, url, title, html, assets=tuple((urljoin(url, name), mime, data) for name, mime, data in assets))
            _save_gallery_output(snapshot, "archivewebpage", relative, {relative: ("application/wacz", output.read_bytes())})


def _save_gallery_output(snapshot, plugin, primary, files):
    from archivebox.core.models import ArchiveResult, Snapshot

    from django.db.models import F

    manifest = {path: {"mimetype": mime, "size": len(data)} for path, (mime, data) in files.items()}
    size = sum(meta["size"] for meta in manifest.values())
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        hook_name="gallery_fixture",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str=primary,
        output_size=size,
        output_files=manifest,
    )
    Snapshot.objects.filter(pk=snapshot.pk).update(output_size=F("output_size") + size)
