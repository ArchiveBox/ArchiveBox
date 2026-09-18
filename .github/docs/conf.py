"""Build the pinned 0.8.6rc1 user guide without importing ArchiveBox or Django."""

import os
import re
from pathlib import Path
from urllib.parse import unquote

from markdown_it import MarkdownIt
from myst_parser.mdit_to_docutils.base import default_slugify

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
project = "ArchiveBox"
author = "ArchiveBox contributors"
copyright = "ArchiveBox contributors"
html_show_sphinx = False
# The release tag is authoritative: its pyproject still declares 0.8.6rc0.
release = "0.8.6rc1"
version = release
extensions = ["myst_parser", "sphinx_rtd_theme", "sphinxcontrib.mermaid"]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
root_doc = "index"
# These are generated autodoc scaffolding, not standalone user documentation.
exclude_patterns = [
    "archivebox*.rst",
    "modules.rst",
    "apidocs/**",
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
html_static_path = [str(DOCS / "_static")]
html_title = f"ArchiveBox {release} documentation"
myst_heading_anchors = 6
myst_fence_as_directive = ["mermaid"]


def prepare_source(app, docname, source):
    """Adapt GitHub wiki navigation in memory, preserving the pinned sources."""
    text = source[0]
    if docname == "Contents":
        text = re.sub(r"API Reference\n#############.*?(?=Meta\n####)", "", text, flags=re.DOTALL)
        text += "\n.. toctree::\n    :hidden:\n\n    Home\n    ArchiveBox-Architecture-Diagrams\n    Upgrading-or-Merging-Archives\n"
    if docname == "index":
        text = text.replace("archivebox info", "archivebox status")
        text = text.replace("pip install archivebox", f"pip install archivebox=={release}")
        text = text.replace("ArchiveBox/ArchiveBox/tree/master", f"ArchiveBox/ArchiveBox/tree/v{release}")
        text = text.replace(
            "`Github <https://github.com/ArchiveBox/ArchiveBox/issues>`_",
            "`GitHub issues <https://github.com/ArchiveBox/ArchiveBox/issues>`_",
        )
        text = text.replace(
            "==========\nArchiveBox\n==========",
            f"ArchiveBox {release}\n" + "=" * (11 + len(release)),
        )
    if app.env.doc2path(docname).endswith(".md"):

        def wiki_link(match):
            parts = match.group(1).split("|", 1)
            label, target = (parts[0], parts[-1])
            page, separator, anchor = unquote(target).partition("#")
            page = page.replace(" ", "-")
            page = {"Setting-Up-Authentication": "Setting-up-Authentication"}.get(page, page)
            suffix = f"#{anchor}" if separator else ""
            return f"[{label}]({page}.md{suffix})"

        text = re.sub(r"\[\[([^\]\n]+)\]\]", wiki_link, text)
    source[0] = text


# GitHub wiki headings allow skipped levels; normalize their hierarchy before MyST
# parses them, without changing fenced code blocks or the historical source files.
def normalize_markdown(app, docname, source):
    if not app.env.doc2path(docname).endswith(".md"):
        return
    text = source[0]
    if docname == "Upgrading":
        text = text.replace("---\n---", "---")
    if docname == "Scheduled-Archiving":
        text = text.replace("```bash\n$ cd", "```console\n$ cd", 1)
    if docname == "Setting-up-Authentication":
        text = text.replace(
            "[Wiki: Configuration (`PUBLIC_ADD_VIEW`, `PUBLIC_SNAPSHOTS`, `PUBLIC_INDEX`)]()",
            "[Wiki: Configuration (`PUBLIC_ADD_VIEW`, `PUBLIC_SNAPSHOTS`, `PUBLIC_INDEX`)](Configuration.md#public_index--public_snapshots--public_add_view)",
        )
    if docname in {"Home", "README", "Donations", "Upgrading-or-Merging-Archives"}:
        text = "# " + ("ArchiveBox overview" if docname == "README" else docname.replace("-", " ")) + "\n\n" + text
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
        lines[line] = re.sub(r"^#{1,6}(?=\s)", "#" * len(stack), lines[line]).replace("\ufe0f", "")
    text = "\n".join(lines) + "\n"

    def link(match):
        target = match.group(1)
        if "://" in target or target.startswith("mailto:"):
            return match.group(0)
        page, sep, anchor = target.partition("#")
        if page and (DOCS / (page + ".md")).exists():
            page += ".md"
        anchor = unquote(anchor).lower()
        if docname == "Install" and not page:
            anchor = {
                "option-a-docker--docker-compose-setup-️": "option-a-docker--docker-compose-setup-",
                "upgrading-archivebox-to-a-new-version": "next-steps-upgrading-archivebox-to-a-new-version",
                "next-steps": "next-steps-add-some-urls-to-archive-and-try-out-cli--web-ui",
                "ubuntudebian": "ubuntudebian-based-systems",
                "bsd": "freebsd",
                "manual-setup": "option-c-bare-metal-setup",
            }.get(anchor, anchor)
        if docname == "README" and not page:
            anchor = {
                "input-formats": "input-formats-how-to-pass-urls-into-archivebox-for-saving",
                "output-formats": "output-formats-what-archivebox-saves-for-each-url",
            }.get(anchor, anchor)
        if (docname == "Configuration" and not page) or page == "Configuration.md":
            other = (DOCS / "Configuration.md").read_text()
            for heading in re.findall(r"^#+\s+(.+)$", other, re.MULTILINE):
                if anchor in [word.lower() for word in re.findall(r"`([^`]+)`", heading)]:
                    anchor = default_slugify(heading.replace("`", ""))
                    break
            aliases = {"templates_dir": "custom_templates_dir"}
            anchor = aliases.get(anchor, anchor)
            if anchor in {
                "search_backend_timeout",
                "search_backend_engine",
                "use_curl",
            }:
                if anchor == "use_curl":
                    # This obsolete wiki option no longer exists in the 0.8 config.
                    return "](Configuration.md#curl_binary)"
                code = (ROOT / "archivebox/config/common.py").read_text().splitlines()
                number = next(i + 1 for i, line in enumerate(code) if anchor.upper() in line)
                return "](https://github.com/ArchiveBox/ArchiveBox/blob/v0.8.6rc1/archivebox/config/common.py#L" + str(number) + ")"
        if docname == "README" and anchor == "saves-lots-of-useful-stuff-for-each-imported-link":
            anchor = "output-formats-what-archivebox-saves-for-each-url"
        if docname == "Web-Archiving-Community":
            anchor = {
                "blogs": "blogs-friends-of-archivebox",
                "articles": "articles-we-like-about-internet-archiving",
            }.get(anchor, anchor)
        return "](" + page + ("#" + anchor if sep else "") + ")"

    text = re.sub(r"\]\(([^)\s]+)\)", link, text)
    # Raw HTML links are outside MyST's cross-reference resolver.
    html_anchors = {
        "background--motivation": "background-motivation",
        "Caveats": "caveats",
        "contents": "web-archiving-community",
        "%EF%B8%8F-cli-usage": "cli-usage",
        "url_whitelist": "url-allowlist",
        "url_blacklist": "url-denylist",
        "input-formats": "input-formats-how-to-pass-urls-into-archivebox-for-saving",
    }
    for old, new in html_anchors.items():
        text = text.replace(f'href="#{old}"', f'href="#{new}"')
    text = text.replace("#️-cli-usage", "#cli-usage")
    source[0] = text


def setup(app):
    app.connect("source-read", prepare_source)
    app.connect("source-read", normalize_markdown)
