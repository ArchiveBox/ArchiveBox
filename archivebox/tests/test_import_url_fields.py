"""Explicit input formats retain literal URL field boundaries through real hooks."""

import csv
import io
import json
from html import escape

import pytest

from .conftest import run_archivebox_cmd, run_python_cwd


@pytest.mark.parametrize("parser", ["json", "jsonl", "rss", "atom", "netscape", "html", "csv", "tsv", "url_list"])
def test_explicit_import_parser_preserves_parentheses(initialized_archive, parser):
    urls = [
        "https://en.wikipedia.org/wiki/APL_(programming_language)",
        "https://example.com/nested_(a_(b))",
        "https://example.com/open(unclosed",
        "https://example.com/close)tail?q=(one)&other=)two",
    ]
    if parser == "json":
        source = json.dumps([{"url": url} for url in urls])
    elif parser == "jsonl":
        source = "\n".join(json.dumps({"url": url}) for url in urls)
    elif parser == "rss":
        source = '<rss version="2.0"><channel><title>URLs</title>'
        source += "".join(f"<item><title>URL</title><link>{escape(url)}</link></item>" for url in urls)
        source += "</channel></rss>"
    elif parser == "atom":
        source = '<feed xmlns="http://www.w3.org/2005/Atom"><title>URLs</title>'
        source += "".join(
            f'<entry><id>{escape(url)}</id><title>URL</title><link href="{escape(url, quote=True)}"/></entry>' for url in urls
        )
        source += "</feed>"
    elif parser in {"netscape", "html"}:
        source = "<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><p>"
        source += "".join(f'<DT><A HREF="{escape(url, quote=True)}">URL</A>' for url in urls)
        source += "</DL>"
    elif parser in {"csv", "tsv"}:
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter="\t" if parser == "tsv" else ",")
        writer.writerow(["url", "title"])
        writer.writerows((url, "Saved URL") for url in urls)
        source = stream.getvalue()
    else:
        source = "\n".join(urls) + "\n\n"
    added = run_archivebox_cmd(
        ["add", "--bg", f"--parser={parser}", "--depth=0"],
        cwd=initialized_archive,
        stdin=source,
    )
    assert added.returncode == 0, added.stdout + added.stderr
    script = """
import asyncio, json, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
import django
django.setup()
from archivebox.crawls.models import Crawl
from archivebox.services.runner import CrawlRunner
crawl = Crawl.objects.get()
runner = CrawlRunner(crawl, show_progress=False)
try:
    ids = runner.load_run_state()
    print(json.dumps({'urls': list(crawl.snapshot_set.values_list('url', flat=True)),
                      'depths': list(crawl.snapshot_set.values_list('depth', flat=True)),
                      'max_depth': crawl.max_depth, 'source': crawl.urls}))
finally:
    asyncio.run(runner.bus.destroy(clear=False))
"""
    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=90)
    assert code == 0, stderr
    result = json.loads(stdout.strip().splitlines()[-1])
    assert set(result["urls"]) == set(urls), result
    assert len(result["urls"]) == len(urls)
    assert result["depths"] == [0] * len(urls)
    assert result["max_depth"] == 0
    assert result["source"] == source
