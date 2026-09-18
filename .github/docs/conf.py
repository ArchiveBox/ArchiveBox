"""Render this release's historical documentation without importing the application."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[2]
release = "0.2.4"
version = release
project = "ArchiveBox"
author = "ArchiveBox contributors"
copyright = "ArchiveBox contributors"
extensions = ["myst_parser", "sphinx_rtd_theme"]
source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = [
    p.name for p in ROOT.iterdir() if p.name not in {"index.md", "docs"}
]
exclude_patterns += ["docs/_Sidebar.md", "docs/_Footer.md", "docs/.git"]
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
    "version_selector": True,
    "language_selector": False,
}
html_context = {"current_version": os.environ.get("READTHEDOCS_VERSION", release)}
html_title = f"ArchiveBox {release} historical documentation"
html_show_sphinx = False
myst_heading_anchors = 6


def prepare_source(app, docname, source):
    text = (ROOT / "README.md").read_text() if docname == "index" else source[0]
    text = text.replace("---\n---", "---")
    text = text.replace("#coookies_file", "#cookies_file")
    if docname == "docs/Home":
        text = text.replace("](#configuration)", "](Configuration.md)")
    if docname == "docs/Troubleshooting":
        text = (
            text.replace("#Dependencies", "#installing")
            .replace("#Archiving", "#archiving")
            .replace("#Hosting-the-Archive", "#hosting-the-archive")
        )
    directory = ROOT if docname == "index" else ROOT / "docs"

    def wiki(match):
        parts = match.group(1).split("|", 1)
        return f"[{parts[0]}]({parts[-1].replace(' ', '-')}.md)"

    text = re.sub(r"\[\[([^\]\n]+)\]\]", wiki, text)

    def resource(target):
        if urlsplit(target).scheme or target.startswith(("#", "//")):
            return target
        page, sep, anchor = target.partition("#")
        path = directory / page
        if path.suffix == ".md" and path.parent == ROOT / "docs":
            return target
        if path.is_file():
            return (
                f"https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/v{release}/{path.relative_to(ROOT)}"
                + ("#" + anchor if sep else "")
            )
        return target

    text = re.sub(
        r'((?:src|href)=["\'])([^"\']+)', lambda m: m[1] + resource(m[2]), text
    )
    text = re.sub(r"\]\(([^)\s]+)\)", lambda m: "](" + resource(m[1]) + ")", text)
    text = (
        f"# ArchiveBox {release}"
        + (
            " historical guide"
            if docname == "index"
            else " — " + Path(docname).name.replace("-", " ")
        )
        + "\n\n"
        + text
    )
    lines = text.splitlines()
    stack = []
    for token in MarkdownIt().parse(text):
        if token.type != "heading_open":
            continue
        original = int(token.tag[1])
        while stack and stack[-1] >= original:
            stack.pop()
        stack.append(original)
        lines[token.map[0]] = re.sub(
            r"^#{1,6}(?=\s)", "#" * len(stack), lines[token.map[0]]
        )
    text = "\n".join(lines) + "\n"
    if docname == "index":
        notice = f"\n```{{warning}}\nThis is the original guide shipped with ArchiveBox {release}, preserved for historical reference. Commands, dependencies, and external services describe that old release and may no longer work. Use the version selector for current documentation.\n```\n"
        first, rest = text.split("\n", 1)
        text = first + "\n" + notice + rest
        pages = sorted(
            p.stem for p in (ROOT / "docs").glob("*.md") if not p.name.startswith("_")
        )
        if pages:
            text += (
                "\n```{toctree}\n:maxdepth: 2\n\n"
                + "\n".join("docs/" + p for p in pages)
                + "\n```\n"
            )
    source[0] = text


def setup(app):
    app.connect("source-read", prepare_source)
