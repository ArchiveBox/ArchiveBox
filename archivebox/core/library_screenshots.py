"""Capture current public news through the real CLI for recurring gallery runs."""

import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import requests
from django.utils import timezone


class NewsLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.urls = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "span" and values.get("class") == "titleline":
            self.in_title = True
        elif tag == "a" and self.in_title:
            url = values.get("href", "")
            if url.startswith(("http://", "https://")) and url not in self.urls:
                self.urls.append(url)
            self.in_title = False


def prepare(evidence_dir):
    from archivebox.config import CONSTANTS
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl

    evidence = Path(evidence_dir)
    evidence.mkdir(parents=True, exist_ok=True)
    response = requests.get("https://news.ycombinator.com/front", timeout=30)
    response.raise_for_status()
    parser = NewsLinks()
    parser.feed(response.text)
    urls = ["https://news.ycombinator.com/", *parser.urls[:3]]
    if len(urls) != 4:
        raise RuntimeError("The live Hacker News front page did not provide three story links.")
    (evidence / "hacker-news-front.html").write_text(response.text)
    (evidence / "hacker-news-urls.json").write_text(json.dumps(urls, indent=2))
    started = timezone.now()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "archivebox",
            "add",
            "--no-only-new",
            "--tag=screenshot-library",
            *urls,
        ],
        cwd=CONSTANTS.DATA_DIR,
        check=True,
    )
    crawl = Crawl.objects.filter(created_at__gte=started, urls__contains=urls[0]).latest("created_at")
    snapshots = list(Snapshot.objects.filter(crawl=crawl))
    if {snapshot.url for snapshot in snapshots} != set(urls):
        raise RuntimeError("Gallery crawl did not create every requested real capture.")
    for snapshot in snapshots:
        if snapshot.status != Snapshot.StatusChoices.SEALED or snapshot.output_size <= 0:
            raise RuntimeError(f"Gallery capture is incomplete: {snapshot.url}")
        if not snapshot.archiveresult_set.filter(plugin="screenshot", status=ArchiveResult.StatusChoices.SUCCEEDED).exists():
            raise RuntimeError(f"Gallery capture has no real screenshot: {snapshot.url}")
        recording = snapshot.archiveresult_set.filter(plugin="archivewebpage", status=ArchiveResult.StatusChoices.SUCCEEDED).first()
        relative = recording.embed_path_db() if recording else ""
        archive = snapshot.output_dir / relative if relative else None
        if archive is None or archive.suffix.lower() != ".wacz" or not archive.is_file() or archive.stat().st_size == 0:
            raise RuntimeError(f"Gallery capture has no successful WACZ recording: {snapshot.url}")
    (evidence / "library-crawl-id.txt").write_text(str(crawl.pk))
    return str(crawl.pk)
