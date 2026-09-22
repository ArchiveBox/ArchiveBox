#!/usr/bin/env python3

import hashlib
import html
import json
import os
import re
import subprocess
import struct
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO_DIR = Path(__file__).resolve().parents[1]
CAPTURE_PROFILES = {
    "desktop": (1600, 1000),
    "tablet": (1024, 1366),
    "mobile": (390, 844),
}

REQUIRED_VIEW_NAMES = {
    "First-time setup wizard",
    "Login",
    "Public snapshot list",
    "Add URLs",
    "Admin dashboard",
    "AI agent",
    "Snapshots table",
    "Snapshots grid",
    "Snapshot admin detail",
    "Snapshot View (capture in progress)",
    "Snapshot View (header collapsed)",
    "Snapshot View (opentimestamps)",
    "Snapshot files",
    "Archive results",
    "Archive result detail",
    "Crawl detail",
    "Crawl schedules",
    "Crawl schedule detail",
    "Persona detail",
    "Machine detail",
    "Network interface detail",
    "Binary detail",
    "Process detail",
    "API tokens",
    "API token detail",
    "Webhooks",
    "Webhook detail",
    "Environment",
    "Configuration",
    "Configuration detail",
    "Dependencies",
    "Dependency detail",
    "Plugins",
    "Workers",
    "Worker detail",
    "Logs",
    "Log detail",
}


def build_provenance() -> dict[str, str]:
    version = tomllib.loads((REPO_DIR / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    revision = os.environ.get("GITHUB_SHA", "").strip()
    if not revision:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    return {
        "version": version,
        "revision": revision,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def validate_navigation(metadata_path: Path, expected_path: str) -> None:
    navigation = json.loads(metadata_path.read_text(encoding="utf-8"))
    navigation = navigation.get("checks", navigation)
    status = navigation.get("status")
    final_url = navigation.get("finalUrl") or ""
    actual_path = urlparse(final_url).path
    if status != 200:
        raise SystemExit(f"expected HTTP 200, got {status}: {final_url or metadata_path}")
    if actual_path != expected_path:
        raise SystemExit(f"expected final path {expected_path}, got {actual_path}: {final_url}")


def append_manifest(manifest_path: Path, screenshot_path: Path) -> None:
    data = screenshot_path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        raise SystemExit(f"not a valid PNG: {screenshot_path}")
    dimensions = struct.unpack(">II", data[16:24])
    profile = os.environ["UI_SCREENSHOT_PROFILE"]
    if profile not in CAPTURE_PROFILES:
        raise SystemExit(f"unknown screenshot profile: {profile}")
    default_width, default_height = CAPTURE_PROFILES[profile]
    expected_dimensions = (
        int(os.environ.get("UI_SCREENSHOT_WIDTH", default_width)),
        int(os.environ.get("UI_SCREENSHOT_HEIGHT", default_height)),
    )
    if dimensions != expected_dimensions:
        raise SystemExit(
            f"expected {expected_dimensions[0]}x{expected_dimensions[1]} for {profile}, "
            f"got {dimensions[0]}x{dimensions[1]}: {screenshot_path}",
        )

    item = {
        "name": os.environ["UI_SCREENSHOT_NAME"],
        "url": os.environ["UI_SCREENSHOT_URL"],
        "source": os.environ["UI_SCREENSHOT_SOURCE"],
        "filename": os.environ["UI_SCREENSHOT_FILENAME"],
        "profile": profile,
        "width": dimensions[0],
        "height": dimensions[1],
    }
    timing_report_path = os.environ.get("UI_SCREENSHOT_TIMING_REPORT", "").strip()
    if timing_report_path:
        timing_report = json.loads(Path(timing_report_path).read_text(encoding="utf-8"))
        ttfb_ms = timing_report.get("checks", {}).get("ttfbMs")
        if isinstance(ttfb_ms, int | float):
            item["ttfb_ms"] = round(ttfb_ms)
    with manifest_path.open("a", encoding="utf-8") as manifest:
        manifest.write(json.dumps(item) + "\n")


def render_gallery(gallery_header: str, gallery_sections: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        + (REPO_DIR / "bin/templates/screenshots-head.html").read_text(encoding="utf-8")
        + "<style>"
        ":root{--ink:#28252a;--muted:#716c74;--accent:#9b2854;--paper:#fcfaf7;--line:#e9e2e3}"
        "*{box-sizing:border-box}body{margin:0;font:16px/1.75 system-ui,sans-serif;"
        "background:var(--paper);color:var(--ink)}.screenshot-content{max-width:1100px;margin:0 auto;padding:28px}"
        "a{color:var(--accent)}h1,h2{line-height:1.15;letter-spacing:-.045em}"
        "article{margin:40px 0 65px}article h2{font-size:29px;margin:0 0 10px}article p{font-size:13px;color:var(--muted);margin:0 0 20px}"
        ".profile-switch{display:flex;flex-wrap:wrap;gap:4px;background:#f0e8eb;border:1px solid var(--line);padding:5px;"
        "border-radius:28px;width:max-content;max-width:100%;margin:30px 0}.profile-switch button{font:600 13px system-ui;"
        "cursor:pointer;border:0;border-radius:22px;background:transparent;color:var(--muted);padding:10px 20px}"
        ".profile-switch button[aria-pressed=true]{background:var(--accent);color:white;box-shadow:0 3px 10px #9b285425}"
        "a:focus-visible,button:focus-visible{outline:3px solid var(--accent);outline-offset:4px}"
        "figure{min-width:0;margin:0 0 20px;padding:18px;border:1px solid var(--line);border-radius:20px;"
        "background:linear-gradient(140deg,#fff,#f8edf2)}figure[hidden]{display:none}"
        ".shot-mobile{max-width:440px;margin-inline:auto}.shot-tablet{max-width:800px;margin-inline:auto}"
        "figcaption{font-size:12px;color:var(--muted);text-align:center;margin:0 0 12px}"
        "img{display:block;width:100%;height:auto;border-radius:8px}code{overflow-wrap:anywhere}"
        "@media(max-width:550px){.screenshot-content{padding:20px}figure{padding:8px;border-radius:12px}.profile-switch button{padding:9px 16px}}"
        "</style></head><body>"
        + (REPO_DIR / "bin/templates/screenshots-header.html").read_text(encoding="utf-8")
        + '<div class="screenshot-content">'
        + gallery_header
        + '<div class="profile-switch" role="group" aria-label="Screenshot viewport">'
        + "".join(
            f'<button type="button" data-viewport="{profile}" aria-pressed="{str(profile == "desktop").lower()}">{profile.title()}</button>'
            for profile in CAPTURE_PROFILES
        )
        + "</div><main>"
        + gallery_sections
        + """</main><script>
const figures = document.querySelectorAll('.shot');
const buttons = document.querySelectorAll('[data-viewport]');
function selectProfile(profile) {
  for (const figure of figures) figure.hidden = figure.dataset.profile !== profile;
  for (const button of buttons) button.setAttribute('aria-pressed', String(button.dataset.viewport === profile));
}
for (const button of buttons) button.addEventListener('click', () => selectProfile(button.dataset.viewport));
selectProfile('desktop');
</script></div>"""
        + (REPO_DIR / "bin/templates/screenshots-footer.html").read_text(encoding="utf-8")
        + "</body></html>\n"
    )


def build_galleries(manifest_path: Path, markdown_path: Path, html_path: Path) -> None:
    provenance = build_provenance()
    source_base_url = f"https://github.com/ArchiveBox/ArchiveBox/blob/{provenance['revision']}/"
    captures = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line]
    allow_partial = os.environ.get("UI_SCREENSHOT_ALLOW_PARTIAL") == "1"
    grouped_captures: list[dict[str, object]] = []
    captures_by_name: dict[str, dict[str, object]] = {}
    for capture in captures:
        group = captures_by_name.get(capture["name"])
        if group is None:
            group = {
                "name": capture["name"],
                "url": capture["url"],
                "source": capture["source"],
                "variants": {},
            }
            captures_by_name[capture["name"]] = group
            grouped_captures.append(group)
        elif group["url"] != capture["url"] or group["source"] != capture["source"]:
            raise SystemExit(f"inconsistent manifest metadata for {capture['name']}")
        variants = group["variants"]
        assert isinstance(variants, dict)
        if capture["profile"] in variants:
            raise SystemExit(f"duplicate {capture['profile']} capture for {capture['name']}")
        variants[capture["profile"]] = capture

    complete_groups = []
    for group in grouped_captures:
        variants = group["variants"]
        assert isinstance(variants, dict)
        missing_profiles = [profile for profile in CAPTURE_PROFILES if profile not in variants]
        if missing_profiles:
            if allow_partial:
                continue
            raise SystemExit(f"missing {', '.join(missing_profiles)} capture for {group['name']}")
        complete_groups.append(group)
    grouped_captures = complete_groups

    if not allow_partial:
        captured_names = set(captures_by_name)
        missing = sorted(REQUIRED_VIEW_NAMES - captured_names)
        if missing:
            raise SystemExit(f"required UI screenshot coverage is missing: {', '.join(missing)}")
        snapshot_output_views = [
            name
            for name in captured_names
            if name.startswith("Snapshot View (")
            and name not in {"Snapshot View (capture in progress)", "Snapshot View (header collapsed)"}
        ]
        if len(snapshot_output_views) < 20:
            raise SystemExit(
                f"expected at least 20 rendered Sweeting.me snapshot outputs, got {len(snapshot_output_views)}",
            )
    markdown_sections = []
    html_sections = []
    for capture in grouped_captures:
        variants = capture["variants"]
        assert isinstance(variants, dict)
        parsed_url = urlparse(str(capture["url"]))
        route = parsed_url.path or "/"
        if parsed_url.fragment:
            route = f"{route}#{parsed_url.fragment}"
        source_url = f"{source_base_url}{capture['source']}"
        ttfb_values = [variant["ttfb_ms"] for variant in variants.values() if isinstance(variant.get("ttfb_ms"), int | float)]
        ttfb_text = f" · ~{round(sum(ttfb_values) / len(ttfb_values))}ms TTFB" if ttfb_values else ""
        markdown_cells = []
        html_figures = []
        for profile in CAPTURE_PROFILES:
            variant = variants[profile]
            width, height = variant["width"], variant["height"]
            label = f"{profile.title()} ({width}x{height})"
            filename = str(variant["filename"])
            screenshot_path = markdown_path.parent / "screenshots" / filename
            if not screenshot_path.is_file():
                raise SystemExit(f"missing screenshot for gallery: {screenshot_path}")
            cache_version = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()[:12]
            versioned_filename = f"{html.escape(filename)}?v={cache_version}"
            markdown_cells.append(
                f'<td align="center"><strong>{label}</strong><br>'
                f'<img src="screenshots/{versioned_filename}" '
                f'alt="{html.escape(str(capture["name"]))} — {profile}" width="{width}"></td>',
            )
            html_figures.append(
                f'<figure class="shot shot-{profile}" data-profile="{profile}"><figcaption>{label}</figcaption>'
                f'<a href="./{versioned_filename}">'
                f'<img src="./{versioned_filename}" width="{width}" height="{height}" loading="lazy" '
                f'alt="{html.escape(str(capture["name"]))} — {profile}"></a></figure>',
            )
        markdown_sections.append(
            "\n".join(
                (
                    f"## {capture['name']}",
                    "",
                    f"View: [`{route}`]({capture['url']}) · [View code]({source_url}){ttfb_text}",
                    "",
                    "<table><thead><tr>",
                    "".join(f"<th>{profile.title()}</th>" for profile in CAPTURE_PROFILES),
                    "</tr></thead><tbody><tr>",
                    "".join(markdown_cells),
                    "</tr></tbody></table>",
                ),
            ),
        )
        html_sections.append(
            f"<article><h2>{html.escape(capture['name'])}</h2>"
            f'<p><a href="{html.escape(capture["url"])}"><code>{html.escape(route)}</code></a> · '
            f'<a href="{html.escape(source_url)}">View code</a>{html.escape(ttfb_text)}</p>'
            f'<div class="shots">{"".join(html_figures)}</div></article>',
        )

    markdown_path.write_text(
        "\n".join(
            (
                "# UI Screenshots",
                "",
                "<!-- Generated by bin/collect_ui_screenshots.sh. Do not edit by hand. -->",
                "",
                (
                    "These desktop, tablet, and mobile screenshots cover ArchiveBox's major public and authenticated UI views. "
                    "Raw API endpoints, API documentation, health-check, and error routes are intentionally excluded."
                ),
                f"Generated from ArchiveBox `{provenance['version']}` at revision `{provenance['revision']}`.",
                "",
                "\n\n".join(markdown_sections),
                "",
            ),
        ),
        encoding="utf-8",
    )

    gallery_header = (
        '<header><p><a href="../">← ArchiveBox</a></p><h1>ArchiveBox UI Screenshots</h1>'
        + f"<p>Generated from ArchiveBox <code>{html.escape(provenance['version'])}</code> at "
        f'<a href="https://github.com/ArchiveBox/ArchiveBox/commit/{html.escape(provenance["revision"])}">'
        f"<code>{html.escape(provenance['revision'][:12])}</code></a> on "
        f'<time datetime="{html.escape(provenance["generated_at"])}">{html.escape(provenance["generated_at"])}</time>. '
        "Desktop, tablet, and mobile viewports are captured from the same build.</p></header>"
    )
    html_path.write_text(render_gallery(gallery_header, "".join(html_sections)), encoding="utf-8")

    file_hashes = {
        capture["filename"]: hashlib.sha256((html_path.parent / capture["filename"]).read_bytes()).hexdigest() for capture in captures
    }
    (html_path.parent / "build.json").write_text(
        json.dumps(
            {
                **provenance,
                "capture_count": len(captures),
                "files": file_hashes,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    if not allow_partial:
        expected_filenames = {capture["filename"] for capture in captures}
        for screenshot_dir in (markdown_path.parent / "screenshots", html_path.parent):
            for screenshot_path in screenshot_dir.glob("*.png"):
                if screenshot_path.name not in expected_filenames:
                    screenshot_path.unlink()


def refresh_gallery(html_path: Path) -> None:
    """Apply current presentation to published capture content without changing provenance."""
    document = html_path.read_text(encoding="utf-8")
    header = re.search(r"<header>.*?</header>", document, re.DOTALL)
    sections = re.search(r"<main>(.*?)</main>", document, re.DOTALL)
    if not header or not sections:
        raise SystemExit("Published screenshot gallery is missing its capture header or content")
    content = sections[1]
    for profile in CAPTURE_PROFILES:
        # Galleries published before the switcher used classes alone.
        content = content.replace(
            f'<figure class="shot shot-{profile}">',
            f'<figure class="shot shot-{profile}" data-profile="{profile}">',
        )
    html_path.write_text(render_gallery(header[0], content), encoding="utf-8")


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "refresh":
        refresh_gallery(Path(sys.argv[2]))
        return
    if len(sys.argv) == 4 and sys.argv[1] == "validate":
        validate_navigation(Path(sys.argv[2]), sys.argv[3])
        return
    if len(sys.argv) == 4 and sys.argv[1] == "append":
        append_manifest(Path(sys.argv[2]), Path(sys.argv[3]))
        return
    if len(sys.argv) == 5 and sys.argv[1] == "build":
        build_galleries(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
        return
    raise SystemExit(
        "usage: generate_ui_screenshot_gallery.py append MANIFEST SCREENSHOT | "
        "validate SCREENSHOT_JSON EXPECTED_PATH | build MANIFEST MARKDOWN HTML",
    )


if __name__ == "__main__":
    main()
