#!/usr/bin/env python3
"""Real user-facing archive flows against live URLs."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest


@pytest.mark.timeout(180)
def test_cli_add_real_urls_with_options_writes_inspectable_outputs(tmp_path, process):
    os.chdir(tmp_path)
    assert process.returncode == 0, process.stderr

    wget_urls = [
        "https://example.com",
        "https://pirate.github.io/stress-tests/challenge.html",
    ]
    chrome_url = "https://example.com/?archivebox-chrome-flow=1"
    env = os.environ.copy()
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "TIMEOUT": "60",
            "SAVE_WGET": "true",
            "SAVE_HEADERS": "false",
            "SAVE_TITLE": "false",
            "SAVE_READABILITY": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_MERCURY": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_PDF": "false",
            "SAVE_DOM": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_FAVICON": "false",
        },
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "archivebox",
            "add",
            "--depth=0",
            "--max-urls=2",
            "--max-size=10mb",
            "--tag=real-flow,challenge",
            "--parser=url_list",
            "--plugins=wget",
            *wget_urls,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    chrome_env = env | {
        "SAVE_WGET": "false",
        "SAVE_HEADERS": "true",
        "SAVE_TITLE": "true",
        "CHROME_HEADLESS": "true",
        "CHROME_SANDBOX": "false",
    }
    install_result = subprocess.run(
        [sys.executable, "-m", "archivebox", "install", "puppeteer"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=chrome_env,
        timeout=180,
    )
    assert install_result.returncode == 0, install_result.stderr or install_result.stdout
    chrome_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "archivebox",
            "add",
            "--depth=0",
            "--max-urls=1",
            "--max-size=10mb",
            "--tag=chrome-flow",
            "--parser=url_list",
            "--plugins=wget,headers,title",
            chrome_url,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=chrome_env,
        timeout=180,
    )
    assert chrome_result.returncode == 0, chrome_result.stderr or chrome_result.stdout

    list_result = subprocess.run(
        [sys.executable, "-m", "archivebox", "list", "--tag=real-flow"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert list_result.returncode == 0, list_result.stderr or list_result.stdout
    listed = [json.loads(line) for line in list_result.stdout.splitlines() if line.strip()]
    assert {item["url"] for item in listed} >= set(wget_urls)

    conn = sqlite3.connect(tmp_path / "index.sqlite3")
    try:
        crawl = conn.execute(
            "SELECT max_depth, max_urls, max_size, tags_str, config FROM crawls_crawl ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        real_flow_crawl = conn.execute(
            "SELECT max_depth, max_urls, max_size, tags_str, config FROM crawls_crawl WHERE tags_str = 'real-flow,challenge'",
        ).fetchone()
        snapshots = conn.execute(
            "SELECT id, url, depth, status, title FROM core_snapshot ORDER BY url",
        ).fetchall()
        archive_results = conn.execute(
            "SELECT s.url, ar.plugin, ar.status, ar.output_files, ar.output_size, ar.output_str "
            "FROM core_archiveresult ar "
            "JOIN core_snapshot s ON s.id = ar.snapshot_id "
            "ORDER BY s.url, ar.plugin",
        ).fetchall()
        processes = conn.execute(
            "SELECT process_type, status, exit_code, pwd, cmd FROM machine_process WHERE process_type = 'hook'",
        ).fetchall()
    finally:
        conn.close()

    assert real_flow_crawl is not None
    assert real_flow_crawl[0] == 0
    assert real_flow_crawl[1] == 2
    assert real_flow_crawl[2] == 10 * 1024 * 1024
    assert real_flow_crawl[3] == "real-flow,challenge"
    assert "wget" in real_flow_crawl[4]
    assert crawl is not None
    assert crawl[3] == "chrome-flow"
    assert "wget,headers,title" in crawl[4]

    snapshot_urls = {url for _id, url, _depth, _status, _title in snapshots}
    assert snapshot_urls >= {*wget_urls, chrome_url}
    assert all(depth == 0 for _id, _url, depth, _status, _title in snapshots)

    by_url_plugin = {(url, plugin): status for url, plugin, status, _files, _size, _output in archive_results}
    assert by_url_plugin[("https://example.com", "wget")] == "succeeded"
    assert by_url_plugin[("https://pirate.github.io/stress-tests/challenge.html", "wget")] == "succeeded"
    assert (chrome_url, "headers") in by_url_plugin
    assert (chrome_url, "title") in by_url_plugin
    failed_results = [(url, plugin, output) for url, plugin, status, _files, _size, output in archive_results if status == "failed"]
    assert len(failed_results) <= 2, failed_results

    snapshot_root = tmp_path / "users/system/snapshots"
    html_outputs = [path for path in snapshot_root.rglob("wget/**/*.html") if path.is_file()]
    header_outputs = [path for path in snapshot_root.rglob("headers/**/headers.json") if path.is_file() and path.stat().st_size > 0]
    title_outputs = [path for path in snapshot_root.rglob("title/title.txt") if path.is_file() and path.stat().st_size > 0]
    index_outputs = [path for path in snapshot_root.rglob("index.jsonl") if path.is_file()]
    assert html_outputs
    if by_url_plugin[(chrome_url, "headers")] == "succeeded":
        assert header_outputs
    if by_url_plugin[(chrome_url, "title")] == "succeeded":
        assert title_outputs
        assert any("Example Domain" in path.read_text(errors="ignore") for path in title_outputs)
    assert len(index_outputs) >= len(wget_urls) + 1

    combined_html = "\n".join(path.read_text(errors="ignore") for path in html_outputs)
    assert "Example Domain" in combined_html
    assert "Browser-use Challenge for AI Browser Drivers" in combined_html

    assert processes
    assert any("wget" in (pwd or "") or "wget" in (cmd or "") for _type, _status, _exit, pwd, cmd in processes)
    assert any("headers" in (pwd or "") or "headers" in (cmd or "") for _type, _status, _exit, pwd, cmd in processes)


@pytest.mark.timeout(180)
def test_cli_recursive_crawl_processes_discovered_html_urls(tmp_path, process):
    os.chdir(tmp_path)
    assert process.returncode == 0, process.stderr

    env = os.environ.copy()
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "TIMEOUT": "60",
            "SAVE_WGET": "true",
            "SAVE_HEADERS": "false",
            "SAVE_TITLE": "false",
            "SAVE_READABILITY": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_MERCURY": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_PDF": "false",
            "SAVE_DOM": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_FAVICON": "false",
            "PARSE_HTML_URLS_ENABLED": "true",
            "PARSE_DOM_OUTLINKS_ENABLED": "false",
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "archivebox",
            "add",
            "--depth=2",
            "--max-urls=2",
            "--max-size=50mb",
            "--tag=recursive-flow",
            "--parser=url_list",
            "--plugins=wget,parse_html_urls",
            "https://example.com",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    conn = sqlite3.connect(tmp_path / "index.sqlite3")
    try:
        crawl = conn.execute(
            "SELECT max_depth, max_urls, max_size, tags_str FROM crawls_crawl ORDER BY created_at DESC LIMIT 1",
        ).fetchone()
        snapshots = conn.execute(
            "SELECT url, depth, status FROM core_snapshot ORDER BY depth, url",
        ).fetchall()
        archive_results = conn.execute(
            "SELECT s.url, ar.plugin, ar.status, ar.output_files "
            "FROM core_archiveresult ar "
            "JOIN core_snapshot s ON s.id = ar.snapshot_id "
            "ORDER BY s.depth, s.url, ar.plugin",
        ).fetchall()
    finally:
        conn.close()

    assert crawl == (2, 2, 50 * 1024 * 1024, "recursive-flow")
    assert ("https://example.com", 0, "sealed") in snapshots
    assert any(url == "https://iana.org/domains/example" and depth == 1 and status == "sealed" for url, depth, status in snapshots)

    by_url_plugin = {(url, plugin): status for url, plugin, status, _files in archive_results}
    assert by_url_plugin[("https://example.com", "wget")] == "succeeded"
    assert by_url_plugin[("https://example.com", "parse_html_urls")] == "succeeded"
    assert by_url_plugin[("https://iana.org/domains/example", "wget")] == "succeeded"

    urls_outputs = list((tmp_path / "users/system/snapshots").rglob("parse_html_urls/urls.jsonl"))
    assert urls_outputs
    assert any("https://iana.org/domains/example" in path.read_text() for path in urls_outputs)
