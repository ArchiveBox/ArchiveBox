"""Acceptance check for a newly initialized disposable collection on symlink-only storage."""

import asyncio
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archivebox.core.settings")
import django


def main():
    django.setup()
    from django.test import RequestFactory
    from django.http import Http404
    from archivebox.services.runner import CrawlRunner
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.misc.serve_static import serve_static_with_byterange_support

    def capture(name):
        url = "https://example.org/" + name
        c = Crawl.objects.create(urls=url, config={"PLUGINS": "hashes", "HASHES_COLLECTION_DEDUP": True})
        s = Snapshot.objects.create(crawl=c, url=url)
        d = s.output_dir / "download"
        d.mkdir(parents=True)
        (d / "note.txt").write_bytes(b"intended")
        (d / "other.txt").write_bytes(b"unrelated")
        asyncio.run(CrawlRunner(c).run())
        return s

    if Snapshot.objects.exists():
        raise ValueError("Run the storage check in an empty disposable collection")
    a = capture("first")
    b = capture("second")
    link = b.output_dir / "download/note.txt"
    assert link.is_symlink()

    def read():
        r = serve_static_with_byterange_support(RequestFactory().get("/download/note.txt?raw=1"), "download/note.txt", b.output_dir)
        try:
            assert r.streaming
            return b"".join(r)
        finally:
            r.close()

    assert read() == b"intended"
    link.unlink()
    link.symlink_to(os.path.relpath(a.output_dir / "download/other.txt", link.parent))
    assert read() == b"unrelated"
    unarchived = a.output_dir / "download/private.txt"
    unarchived.write_bytes(b"unarchived")
    link.unlink()
    link.symlink_to(os.path.relpath(unarchived, link.parent))
    try:
        read()
    except Http404:
        print("Scoped symlink replay passed")
    else:
        raise AssertionError("unarchived target accepted")


if __name__ == "__main__":
    main()
