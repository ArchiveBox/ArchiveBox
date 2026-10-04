#!/usr/bin/env -S uv run --no-project --script
import pathlib
import re
import sys
from urllib.parse import unquote, urlsplit

p = pathlib.Path(sys.argv[1])
text = p.read_text()
if p.suffix not in (".md", ".html", ".rst"):
    # Preserve source line numbers, but feed only literal documentation URLs to Lychee.
    pattern = r'https?://(?:github\.com/(?:ArchiveBox|pirate)/ArchiveBox(?:/wiki|/?#)|docs\.archivebox\.io)[^\s<>\)\]"\x27`\\\[]*'
    text = "\n".join(" ".join(u for u in re.findall(pattern, line) if not re.search(r"[{}]", u)) for line in text.splitlines())
if p.suffix == ".md" and p.parent.name == "docs":
    pages = {page.stem.lower(): page.stem for page in p.parent.glob("*.md")}

    def wikilink(match):
        label, _, target = match[1].partition("|")
        page, sep, fragment = (target or label).replace(" ", "-").partition("#")
        page = pages.get(page.lower(), page)
        return f"[{label}]({page}.md{sep}{fragment})"

    text = re.sub(r"\[\[([^]\n]+)\]\]", wikilink, text)
if p.suffix == ".md":
    # Lychee folds local Markdown fragments to lowercase; GitHub heading IDs are lowercase.
    # Preserve explicitly declared mixed-case HTML IDs, but reject heading case typos.
    errors = []
    for match in re.finditer(r'\]\(([^\s)]+)\)|href=["\']([^"\']+)', text):
        url = urlsplit(match[1] or match[2])
        fragment = unquote(url.fragment)
        if url.scheme or url.netloc or fragment == fragment.lower():
            continue
        target = p.parent / unquote(url.path) if url.path else p
        if not target.suffix:
            target = target.with_suffix(".md")
        if target.suffix != ".md" or not target.is_file():
            continue  # Lychee handles missing files and non-Markdown targets.
        ids = re.findall(r'(?:id|name)=["\']([^"\']+)', target.read_text())
        if fragment not in ids:
            line = text[: match.start()].count("\n") + 1
            errors.append(f"{p}:{line}: heading fragment #{fragment} must match lowercase GitHub IDs")
    if errors:
        sys.exit("\n".join(errors))
print(text)
