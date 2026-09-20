"""Render homepage screenshot strips from the site's existing gallery HTML."""

import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urljoin


class Gallery(HTMLParser):
    """Only gallery figures are captures; navigation and decorative images are not."""

    def __init__(self, base):
        super().__init__()
        self.base = base
        self.stack = []
        self.captures = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img" and any(name == "figure" for name, _ in self.stack):
            context = [item for _, item in self.stack]
            profile = next(
                (
                    item.get("data-profile") or item.get("data-viewport")
                    for item in reversed(context)
                    if item.get("data-profile") or item.get("data-viewport")
                ),
                None,
            )
            if profile not in (None, "desktop"):
                return
            source = attrs.get("src", "")
            if not source or not attrs.get("alt"):
                return
            anchor = next((item["id"] for name, item in reversed(self.stack) if name in ("article", "figure") and item.get("id")), "")
            server = any(item.get("data-platform") == "server" for item in context)
            self.captures.append(
                {
                    "src": urljoin(self.base, source),
                    "href": self.base + "#" + anchor if anchor else urljoin(self.base, source),
                    "title": attrs["alt"],
                    "width": attrs.get("width", ""),
                    "height": attrs.get("height", ""),
                    "product": "server" if server else "client",
                },
            )
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def render(output, baseurl=""):
    homepage = output / "index.html"
    text = homepage.read_text()
    slots = re.findall(r"<!-- ARCHIVEBOX:(MARQUEE(?:-CLIENT|-SERVER)?) -->", text)
    if not slots:
        return False
    base = "/" + baseurl.strip("/") + "/" if baseurl.strip("/") else "/"
    gallery = Gallery(base + "screenshots/")
    gallery.feed((output / "screenshots/index.html").read_text())
    for slot in slots:
        product = slot.removeprefix("MARQUEE-").lower() if "-" in slot else None
        captures = [capture for capture in gallery.captures if product is None or capture["product"] == product]
        cards = []
        for capture in captures:
            dimensions = "".join(f' {key}="{escape(capture[key])}"' for key in ("width", "height") if capture[key])
            cards.append(
                f'<a class="abx-marquee-card" href="{escape(capture["href"])}"><img src="{escape(capture["src"])}" alt="{escape(capture["title"])}"{dimensions} loading="lazy" decoding="async"><span>{escape(capture["title"])}</span></a>',
            )
        viewport_id = slot.lower()
        content = (
            f'<section class="abx-marquee" aria-label="App screenshots"><div class="abx-marquee-controls"><a href="{base}screenshots/{"#gallery-server" if product == "server" else ""}">Explore screenshots →</a><button type="button" class="abx-marquee-toggle" aria-controls="{viewport_id}" hidden>Pause screenshots</button></div><div class="abx-marquee-viewport" id="{viewport_id}" tabindex="0" aria-label="Screenshots. Scroll sideways to explore."><div class="abx-marquee-track">{"".join(cards)}</div></div></section>'
            if cards
            else ""
        )
        start, end = f"<!-- ARCHIVEBOX:{slot} -->", f"<!-- /ARCHIVEBOX:{slot} -->"
        replacement = start + "\n" + content + "\n" + end
        if end in text:
            text = re.sub(
                re.escape(start) + r".*?" + re.escape(end),
                lambda _, replacement=replacement: replacement,
                text,
                count=1,
                flags=re.DOTALL,
            )
        else:
            text = text.replace(start, replacement, 1)
    homepage.write_text(text)
    return True
