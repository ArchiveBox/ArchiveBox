"""Build a pinned historical user guide without importing ArchiveBox or Django."""

import json
import os
import re
from pathlib import Path
from urllib.parse import unquote

from docutils import nodes
from markdown_it import MarkdownIt
from myst_parser.mdit_to_docutils.base import default_slugify

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
project = "ArchiveBox"
author = "ArchiveBox contributors"
copyright = "ArchiveBox contributors"
html_show_sphinx = False
release = json.loads((ROOT / "package.json").read_text())["version"]
version = release
extensions = ["myst_parser", "sphinx_rtd_theme"]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
root_doc = "index"
# These are generated autodoc scaffolding, not standalone user documentation.
exclude_patterns = [
    "archivebox*.rst",
    "modules.rst",
    "_Sidebar.md",
    "_Footer.md",
    ".git",
]
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
    "version_selector": True,
    "language_selector": False,
}
html_context = {"current_version": os.environ.get("READTHEDOCS_VERSION", release)}
html_logo = str(DOCS / "logo.png")
html_static_path = [
    str(path)
    for path in (DOCS / "_static", ROOT / ".github/docs/static")
    if path.is_dir()
]
html_title = f"ArchiveBox {release} documentation"
myst_heading_anchors = 6


def rewrite_prose(text, transform):
    """Rewrite navigation outside fenced and indented code blocks."""
    lines = text.splitlines(keepends=True)
    output = []
    start = 0
    for token in MarkdownIt().parse(text):
        if token.type not in {"fence", "code_block"}:
            continue
        first, last = token.map
        output.append(transform("".join(lines[start:first])))
        output.append("".join(lines[first:last]))
        start = last
    output.append(transform("".join(lines[start:])))
    return "".join(output)


def prepare_source(app, docname, source):
    """Adapt GitHub wiki navigation in memory, preserving the pinned sources."""
    text = source[0]
    if docname == "Contents":
        text = re.sub(
            r"API Reference\n#############.*?(?=Meta\n####)", "", text, flags=re.DOTALL
        )
        text += "\n.. toctree::\n    :hidden:\n\n    Home\n"
    if docname == "index":
        text = text.replace("archivebox info", "archivebox status")
        text = text.replace(
            "pip install archivebox", f"pip install archivebox=={release}"
        )
        text = text.replace(
            "ArchiveBox/ArchiveBox/tree/master",
            f"ArchiveBox/ArchiveBox/tree/v{release}",
        )
        text = text.replace(
            "`Github <https://github.com/ArchiveBox/ArchiveBox/issues>`_",
            "`GitHub issues <https://github.com/ArchiveBox/ArchiveBox/issues>`_",
        )
        text = text.replace(
            "==========\nArchiveBox\n==========",
            f"ArchiveBox {release}\n" + "=" * (11 + len(release)),
        )
    if Path(app.env.doc2path(docname)).suffix == ".md":

        def wiki_link(match):
            parts = match.group(1).split("|", 1)
            label, target = (parts[0], parts[-1])
            page, separator, anchor = unquote(target).partition("#")
            page = page.replace(" ", "-")
            suffix = f"#{anchor}" if separator else ""
            return f"[{label}]({page}.md{suffix})"

        def adapt_prose(prose):
            prose = re.sub(r"\[\[([^\]\n]+)\]\]", wiki_link, prose)
            return re.sub(
                r"(https://github\.com/ArchiveBox/ArchiveBox/blob/)(?:master|v0\.7\.4)(/)",
                rf"\g<1>v{release}\2",
                prose,
            )

        text = rewrite_prose(text, adapt_prose)
    source[0] = text


# GitHub wiki headings allow skipped levels; normalize their hierarchy before MyST
# parses them, without changing fenced code blocks or the historical source files.
def normalize_markdown(app, docname, source):
    if Path(app.env.doc2path(docname)).suffix != ".md":
        return
    text = source[0]
    text = re.sub(r"(?m)^(`{3,})bash(?:\[\]\[\]|\|)(?=\s|$)", r"\1bash", text)
    text = re.sub(r"(?m)^(`{3,})python3(?=\s|$)", r"\1bash", text)
    if docname in {"Home", "README", "Donations", "Upgrading-or-Merging-Archives"}:
        text = (
            "# "
            + (
                "ArchiveBox overview"
                if docname == "README"
                else docname.replace("-", " ")
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
        line = token.map[0]
        lines[line] = re.sub(r"^#{1,6}(?=\s)", "#" * len(stack), lines[line]).replace(
            "\ufe0f", ""
        )
    text = "\n".join(lines) + "\n"

    def link(match):
        target = match.group(1)
        if "://" in target or target.startswith("mailto:"):
            return match.group(0)
        page, sep, anchor = target.partition("#")
        if page and (DOCS / (page + ".md")).exists():
            page += ".md"
        # MyST resolves Markdown GitHub slugs (e.g. background--motivation)
        # to rendered section IDs; raw HTML links below need explicit rewrites.
        anchor = anchor.lower()
        if (docname == "Configuration" and not page) or page == "Configuration.md":
            other = (DOCS / "Configuration.md").read_text()
            for heading in re.findall(r"^#+\s+(.+)$", other, re.MULTILINE):
                if anchor in [
                    word.lower() for word in re.findall(r"`([^`]+)`", heading)
                ]:
                    anchor = default_slugify(heading.replace("`", ""))
                    break
            aliases = {}
            if any(
                default_slugify(heading.replace("`", "")) == "custom_templates_dir"
                for heading in re.findall(r"^#+\s+(.+)$", other, re.MULTILINE)
            ):
                aliases["templates_dir"] = "custom_templates_dir"
            anchor = aliases.get(anchor, anchor)
            if anchor in {
                "search_backend_timeout",
                "search_backend_engine",
                "use_curl",
            }:
                code = (ROOT / "archivebox/config.py").read_text().splitlines()
                number = next(
                    i + 1 for i, line in enumerate(code) if anchor.upper() in line
                )
                return (
                    f"](https://github.com/ArchiveBox/ArchiveBox/blob/v{release}/archivebox/config.py#L"
                    + str(number)
                    + ")"
                )
        if (
            docname == "README"
            and anchor == "saves-lots-of-useful-stuff-for-each-imported-link"
        ):
            anchor = "output-formats"
        if docname == "README" and not page and anchor == "screenshots":
            page, anchor = "Usage.md", "ui-usage"
        if docname == "Web-Archiving-Community":
            alias = {
                "blogs": "blogs-friends-of-archivebox",
                "articles": "articles-we-like-about-internet-archiving",
            }.get(anchor)
            headings = {
                default_slugify(heading.replace("`", ""))
                for heading in re.findall(r"^#+\s+(.+)$", text, re.MULTILINE)
            }
            if alias in headings:
                anchor = alias
        if docname == "Usage":
            aliases = {
                "overview": "usage",
                "import-a-single-url-or-list-of-urls-via-stdin": "import-a-single-url",
                "import-list-of-links-exported-from-browser-or-another-service": "import-list-of-links-from-browser-history",
                "import-list-of-urls-from-a-remote-rss-feed-or-file": "import-a-list-of-urls-from-a-txt-file",
            }
            alias = aliases.get(anchor)
            headings = {
                default_slugify(heading.replace("`", ""))
                for heading in re.findall(r"^#+\s+(.+)$", text, re.MULTILINE)
            }
            if alias in headings:
                anchor = alias
        if docname == "Docker" and not page and anchor == "":
            anchor = "overview"
        return "](" + page + ("#" + anchor if sep else "") + ")"

    def rewrite_links(prose):
        prose = re.sub(r"\]\(([^)\s]+)\)", link, prose)
        # Raw HTML links are outside MyST's cross-reference resolver.
        html_anchors = {
            "background--motivation": "background-motivation",
            "Caveats": "caveats",
            "contents": "web-archiving-community",
            "%EF%B8%8F-cli-usage": "cli-usage",
        }
        for old, new in html_anchors.items():
            prose = prose.replace(f'href="#{old}"', f'href="#{new}"')
        if docname == "README":
            prose = prose.replace('href="#screenshots"', 'href="Usage.html#ui-usage"')
        prose = prose.replace("#️-cli-usage", "#cli-usage")
        return prose

    text = rewrite_prose(text, rewrite_links)
    source[0] = text


def add_heading_aliases(app, doctree, docname):
    """Keep incoming GitHub fragments valid alongside MyST's heading IDs."""
    targets = {identifier: node for node in doctree.findall(nodes.Element) for identifier in node.get("ids", [])}
    aliases = {slug: target for slug, (_, target, _) in app.env.metadata.get(docname, {}).get("myst_slugs", {}).items()}
    for alias, target in aliases.items():
        if alias not in targets and target in targets:
            targets[target]["ids"].append(alias)


def setup(app):
    app.connect("source-read", prepare_source)
    app.connect("source-read", normalize_markdown)
    app.connect("doctree-resolved", add_heading_aliases)
