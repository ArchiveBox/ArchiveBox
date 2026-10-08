"""Check links and fragments in a real Sphinx HTML build, without network requests."""

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.ids = set()
        self.links = set()
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("name"):
            self.ids.add(attrs["name"])
        for key in ("href", "src"):
            if attrs.get(key):
                self.links.add(attrs[key])


def main():
    root = Path(sys.argv[1]).resolve()
    pages = {path: Page(path) for path in root.rglob("*.html")}
    if not pages:
        raise SystemExit(f"No HTML pages found in {root}")
    errors = []
    for path, page in pages.items():
        for link in sorted(page.links):
            url = urlsplit(link)
            # External URLs and site-root routes belong to the hosting service.
            if url.scheme or url.netloc or url.path.startswith("/"):
                continue
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if target.is_dir():
                target /= "index.html"
            fragment = unquote(url.fragment).split(":~:text=", 1)[0]
            if not target.exists():
                errors.append(f"{path.relative_to(root)}: missing file {link}")
            elif fragment and target in pages and fragment not in pages[target].ids:
                errors.append(f"{path.relative_to(root)}: missing fragment {link}")
    for error in sorted(errors):
        print(error)
    print(f"Checked {len(pages)} HTML pages: {len(errors)} broken local links")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
