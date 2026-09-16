"""Transform captured text, Markdown, and images into replay documents.

HTTP caching, range requests, and replay security headers belong to serve_static;
these helpers only render content and resolve references to captured responses.
"""

import html
import posixpath
import re
from pathlib import Path
from urllib.parse import quote, urljoin

from markdown_it import MarkdownIt

IMG_SRC_ATTR_RE = re.compile(r'(<img\b[^>]*?\s(?:src|data-src)=["\'])([^"\']+)(["\'])', re.IGNORECASE)


TRANSFORMED_HTML_PREVIEW_STYLE = """<style id="archivebox-static-html-preview-style">
html {
    width: 100%;
    min-width: 100%;
    background: #fff;
}
body {
    box-sizing: border-box;
    width: min(100%, 72rem);
    max-width: none;
    min-height: 100vh;
    margin: 0 auto;
    padding: clamp(1rem, 3vw, 2rem);
    background: #fff;
    color: #111827;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.55;
}
body > * {
    max-width: 100%;
}
img:not([width]):not([height]) {
    max-width: min(100%, 12rem);
    max-height: 12rem;
    width: auto;
    height: auto;
    object-fit: contain;
}
a > img:not([width]):not([height]) {
    max-width: min(100%, 2.5rem);
    max-height: 2.5rem;
}
</style>"""


MARKDOWN_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+(?:\([^)]*\)[^)\s]*)*)\)")


HTML_BODY_RE = re.compile(r"<body[^>]*>(.*)</body>", flags=re.IGNORECASE | re.DOTALL)


def _extract_markdown_candidate(text: str) -> str:
    candidate = text
    body_match = HTML_BODY_RE.search(candidate)
    if body_match:
        candidate = body_match.group(1)
    candidate = re.sub(r"^\s*<p[^>]*>", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"</p>\s*$", "", candidate, flags=re.IGNORECASE)
    return candidate.strip()


def _looks_like_markdown(text: str) -> bool:
    lower = text.lower()
    if "<html" in lower and "<head" in lower and "</body>" in lower:
        return False
    md_markers = 0
    md_markers += len(re.findall(r"^\s{0,3}#{1,6}\s+\S", text, flags=re.MULTILINE))
    md_markers += len(re.findall(r"^\s*[-*+]\s+\S", text, flags=re.MULTILINE))
    md_markers += len(re.findall(r"^\s*\d+\.\s+\S", text, flags=re.MULTILINE))
    md_markers += text.count("[TOC]")
    md_markers += len(MARKDOWN_INLINE_LINK_RE.findall(text))
    md_markers += text.count("\n---") + text.count("\n***")
    return md_markers >= 6


def _render_text_preview_document(text: str, title: str) -> str:
    escaped_title = html.escape(title)
    escaped_text = html.escape(text)
    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escaped_title}</title>
    <style>
        :root {{
            color-scheme: dark;
        }}
        html, body {{
            margin: 0;
            padding: 0;
            background: #111;
            color: #f3f3f3;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
        }}
        .archivebox-text-preview-header {{
            position: sticky;
            top: 0;
            z-index: 1;
            padding: 10px 14px;
            font-size: 12px;
            line-height: 1.4;
            color: #bbb;
            background: rgba(17, 17, 17, 0.96);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(8px);
        }}
        .archivebox-text-preview {{
            margin: 0;
            padding: 14px;
            white-space: pre-wrap;
            word-break: break-word;
            tab-size: 2;
            line-height: 1.45;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="archivebox-text-preview-header">{escaped_title}</div>
    <pre class="archivebox-text-preview">{escaped_text}</pre>
</body>
</html>"""


def _render_image_preview_document(image_url: str, title: str) -> str:
    escaped_title = html.escape(title)
    escaped_url = html.escape(image_url, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escaped_title}</title>
    <style>
        :root {{
            color-scheme: dark;
        }}
        html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            min-height: 100%;
            background: #fff;
        }}
        body {{
            overflow: auto;
        }}
        .archivebox-image-preview {{
            width: 100%;
            min-width: 100%;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-start;
            box-sizing: border-box;
        }}
        .archivebox-image-preview img {{
            display: block;
            width: auto;
            max-width: 100%;
            height: auto;
            margin: 0 auto;
        }}
    </style>
</head>
<body>
    <div class="archivebox-image-preview">
        <img src="{escaped_url}" alt="{escaped_title}">
    </div>
</body>
</html>"""


def _encoded_responses_image_url(image_url: str, page_url: str | None) -> str | None:
    raw_url = str(image_url or "").strip()
    if not raw_url or raw_url.startswith(("#", "data:", "blob:", "about:", "javascript:")):
        return None

    absolute_url = urljoin(page_url or "", raw_url)
    if not absolute_url.startswith(("http://", "https://")):
        return None

    return quote(absolute_url, safe="").replace("%", "_")


def _index_responses_paths_for_html_images(
    snapshot_root: Path,
    html_rel_path: str,
    encoded_urls: set[str],
) -> dict[str, str]:
    responses_root = snapshot_root / "responses"
    if not encoded_urls or not responses_root.is_dir():
        return {}

    best_matches: dict[str, str] = {}
    image_matches: set[str] = set()
    image_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"}
    for candidate in responses_root.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            rel_path = candidate.relative_to(snapshot_root)
        except ValueError:
            continue
        relative_match = posixpath.relpath(rel_path.as_posix(), start=posixpath.dirname(html_rel_path) or ".")
        candidate_name = candidate.name
        is_image = candidate.suffix.lower() in image_suffixes
        for encoded_url in encoded_urls:
            if encoded_url in image_matches or f"__GET__{encoded_url}" not in candidate_name:
                continue
            best_matches[encoded_url] = relative_match
            if is_image:
                # Preserve the old rglob behavior: the first image match wins,
                # otherwise the last matching response file is used.
                image_matches.add(encoded_url)
    return best_matches


def _rewrite_html_image_sources_to_responses(
    html_text: str,
    snapshot_root: Path,
    html_rel_path: str,
    page_url: str | None,
) -> tuple[str, int]:
    encoded_urls_by_src: dict[str, str | None] = {}
    for match in IMG_SRC_ATTR_RE.finditer(html_text):
        image_url = html.unescape(match.group(2))
        if image_url not in encoded_urls_by_src:
            encoded_urls_by_src[image_url] = _encoded_responses_image_url(image_url, page_url)

    response_paths = _index_responses_paths_for_html_images(
        snapshot_root,
        html_rel_path,
        {encoded_url for encoded_url in encoded_urls_by_src.values() if encoded_url},
    )
    rewrites = 0

    def replace_src(match: re.Match[str]) -> str:
        nonlocal rewrites
        image_url = html.unescape(match.group(2))
        encoded_url = encoded_urls_by_src.get(image_url)
        local_path = response_paths.get(encoded_url or "")
        if not local_path:
            return match.group(0)
        rewrites += 1
        return f"{match.group(1)}{html.escape(local_path, quote=True)}{match.group(3)}"

    return IMG_SRC_ATTR_RE.sub(replace_src, html_text), rewrites


def _rewrite_html_image_sources_for_request(
    request,
    html_text: str,
    document_root: Path | None,
    html_rel_path: str,
) -> tuple[str, int]:
    if not document_root:
        return html_text, 0
    return _rewrite_html_image_sources_to_responses(
        html_text,
        document_root,
        html_rel_path,
        request.__dict__.get("archivebox_snapshot_url"),
    )


def _apply_transformed_html_preview_style(html_text: str) -> str:
    if "archivebox-static-html-preview-style" in html_text:
        return html_text
    if re.search(r"</head\s*>", html_text, flags=re.IGNORECASE):
        return re.sub(r"</head\s*>", f"{TRANSFORMED_HTML_PREVIEW_STYLE}\\g<0>", html_text, count=1, flags=re.IGNORECASE)
    return f"{TRANSFORMED_HTML_PREVIEW_STYLE}\n{html_text}"


def _render_markdown(markdown_text: str) -> str:
    """Render archived Markdown with stable heading links and optional [TOC]."""
    parser = MarkdownIt("commonmark").enable("table")
    tokens = parser.parse(markdown_text)
    headings = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            title = tokens[index + 1].content
            slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-") or "section"
            token.attrSet("id", slug)
            headings.append(f'<li class="toc-level-{token.tag[1:]}"><a href="#{slug}">{html.escape(title)}</a></li>')
    toc = '<nav class="toc"><ul>' + "".join(headings) + "</ul></nav>"
    # Replace only a standalone TOC paragraph, leaving code and inline mentions intact.
    for index in range(len(tokens) - 2):
        opening, content, closing = tokens[index : index + 3]
        if opening.type == "paragraph_open" and content.content == "[TOC]" and closing.type == "paragraph_close":
            opening.hidden = closing.hidden = True
            content.type = "html_block"
            content.content = toc
    return parser.renderer.render(tokens, parser.options, {})


def _render_markdown_document(markdown_text: str) -> str:
    body = _render_markdown(markdown_text)
    wrapped = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<style>body{max-width:900px;margin:24px auto;padding:0 16px;"
        "font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        "line-height:1.55;} img{max-width:100%;} pre{background:#f6f6f6;padding:12px;overflow:auto;}"
        ".toc ul{list-style:none;padding-left:0;} .toc li{margin:4px 0;}</style>"
        "</head><body>"
        f"{body}"
        "</body></html>"
    )
    return wrapped
