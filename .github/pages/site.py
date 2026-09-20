"""Assemble and verify this repository's static Pages site (standard library only)."""

import argparse
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from marquee import render as render_marquee

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def replace_block(text, name, content):
    start, end = f"<!-- ARCHIVEBOX:{name} -->", f"<!-- /ARCHIVEBOX:{name} -->"
    pattern = re.escape(start) + r".*?" + re.escape(end)
    if re.search(pattern, text, re.DOTALL):
        return re.sub(
            pattern,
            lambda _: f"{start}\n{content}\n{end}",
            text,
            count=1,
            flags=re.DOTALL,
        )
    if text.count(start) != 1:
        raise ValueError(f"Expected one {name} placeholder")
    return text.replace(start, f"{start}\n{content}\n{end}", 1)


def render_metadata(text):
    """Keep product copy in native templates; render one consistent SEO block."""
    page = Page()
    page.feed(text)
    title = unescape(re.search(r"<title>(.*?)</title>", text, re.DOTALL)[1])
    meta = page.metadata
    description = meta.get("description", meta.get("og:description", ""))
    image = meta.get("og:image", meta.get("twitter:image", ""))
    if not description or not image or not page.canonical:
        raise ValueError("Each page needs a description, social image and canonical")
    values = {
        "description": description,
        "robots": "index,follow,max-image-preview:large",
        "theme-color": "#9b2854",
        "og:type": "website",
        "og:site_name": meta.get("og:site_name", "ArchiveBox"),
        "og:locale": meta.get("og:locale", "en_US"),
        "og:url": page.canonical,
        "og:title": title,
        "og:description": description,
        "og:image": image,
        "og:image:type": meta.get("og:image:type", "image/png"),
        "og:image:width": meta.get("og:image:width", "1200"),
        "og:image:height": meta.get("og:image:height", "630"),
        "og:image:alt": meta.get("og:image:alt", title),
        "twitter:card": "summary_large_image",
        "twitter:site": "@ArchiveBoxApp",
        "twitter:title": title,
        "twitter:description": description,
        "twitter:image": image,
        "twitter:image:alt": meta.get("og:image:alt", title),
    }

    def strip_managed_tag(match):
        tag = Page()
        tag.feed(match[0])
        if tag.canonicals or any(key in values for key in tag.metadata):
            return ""
        # System fonts are shared across sites, without a network font dependency.
        if "fonts.googleapis.com" in match[0] or "fonts.gstatic.com" in match[0]:
            return ""
        return match[0]

    text = re.sub(r"<(?:meta|link)\b[^>]*>", strip_managed_tag, text)
    text = re.sub(r"<title>.*?</title>", "", text, flags=re.DOTALL)
    tags = [
        f"<title>{escape(title)}</title>",
        f'<link rel="canonical" href="{escape(page.canonical, quote=True)}">',
    ]
    for key, value in values.items():
        attr = "property" if key.startswith("og:") else "name"
        tags.append(f'<meta {attr}="{key}" content="{escape(value, quote=True)}">')
    if "<!-- ARCHIVEBOX:METADATA -->" not in text:
        text = text.replace("</head>", "<!-- ARCHIVEBOX:METADATA -->\n</head>", 1)
    return replace_block(text, "METADATA", "\n".join(tags))


def render(output, source=None, baseurl=""):
    config = json.loads((HERE / "site.json").read_text())
    output = output.resolve()
    if source:
        source = source.resolve()
        if output == source or output in source.parents or source in output.parents:
            raise ValueError("Build output must be separate from the source directory")
        if output == ROOT or output in ROOT.parents:
            raise ValueError("Build output must not replace a repository")
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(source, output)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assets = output / "site-base"
    assets.mkdir(parents=True, exist_ok=True)
    has_marquee = render_marquee(output, baseurl)
    common_assets = ["chrome.css", "chrome.js"] + (["marquee.css", "marquee.js"] if has_marquee else [])
    for name in common_assets:
        shutil.copyfile(HERE / "base" / name, assets / name)
    for name in config["pages"]:
        page = output / name
        text = render_metadata(page.read_text())
        base = "../" * (len(Path(name).parts) - 1) or "./"
        header = (HERE / "base/header.html").read_text().replace("__SITE_NAME__", escape(config["name"]))
        header = header.replace("__SITE_NAV__", (HERE / "nav.html").read_text().strip())
        text = replace_block(text, "HEADER", header)
        for kind in ["FOOTER-START", "FOOTER-END"]:
            text = replace_block(text, kind, (HERE / "base" / f"{kind.lower()}.html").read_text().strip())
        text = text.replace("__SITE_BASE__", base).replace("__SITE_REVISION__", revision)
        resources = f'<link rel="stylesheet" href="{base}site-base/chrome.css?v={revision}">\n<script src="{base}site-base/chrome.js?v={revision}" defer></script>'
        if has_marquee and name == "index.html":
            resources += f'\n<link rel="stylesheet" href="{base}site-base/marquee.css?v={revision}">\n<script src="{base}site-base/marquee.js?v={revision}" defer></script>'
        if "<!-- ARCHIVEBOX:ASSETS -->" not in text:
            text = text.replace("</head>", "<!-- ARCHIVEBOX:ASSETS -->\n</head>", 1)
        text = replace_block(text, "ASSETS", resources)
        page.write_text(text)
    # Site build provenance is independent of all original screenshot manifests.
    provenance_path = output / "build.json"
    provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else {}
    provenance.update(
        revision=revision,
        generatedAt=datetime.now(UTC).isoformat(),
        site=config["url"],
    )
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")
    (output / ".nojekyll").touch()
    verify(output, baseurl)
    print(f"Assembled {len(config['pages'])} pages at {output} from {revision}")


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.metadata = {}
        self.canonical = ""
        self.resources = []
        self.headers = self.footers = self.canonicals = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            for key in ["name", "property"]:
                if attrs.get(key):
                    self.metadata[attrs[key]] = attrs.get("content", "")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs["href"]
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        classes = attrs.get("class", "").split()
        self.headers += "abx-header" in classes
        self.footers += "abx-footer" in classes
        self.canonicals += tag == "link" and attrs.get("rel") == "canonical"
        if tag in ["img", "script"] and attrs.get("src"):
            self.resources.append(attrs["src"])
        if tag == "link" and attrs.get("rel") in [
            "stylesheet",
            "icon",
            "apple-touch-icon",
        ]:
            self.resources.append(attrs["href"])


def verify(output, baseurl=""):
    config = json.loads((HERE / "site.json").read_text())
    output = output.resolve()
    prefix = "/" + baseurl.strip("/") if baseurl.strip("/") else ""
    for name in config["pages"]:
        path = output / name
        text = path.read_text()
        page = Page()
        page.feed(text)
        if (page.headers, page.footers, page.canonicals) != (1, 1, 1):
            raise ValueError(f"{name}: expected exactly one shared header, footer and canonical")
        if "__SITE_" in text:
            raise ValueError(f"{name}: unresolved site placeholder")
        for resource in page.resources:
            url = urlsplit(resource)
            if url.scheme or url.netloc or not url.path:
                continue
            resource_path = unquote(url.path)
            if prefix and resource_path.startswith(prefix + "/"):
                resource_path = resource_path[len(prefix) :]
            local = (output / resource_path.lstrip("/") if resource_path.startswith("/") else path.parent / resource_path).resolve()
            if not local.is_relative_to(output) or not local.is_file():
                raise ValueError(f"{name}: missing local resource {resource}")
        for asset in ["chrome.css", "chrome.js"]:
            if (output / "site-base" / asset).read_bytes() != (HERE / "base" / asset).read_bytes():
                raise ValueError(f"{name}: stale common asset {asset}")
    print(f"Verified shared layout and local resources for {len(config['pages'])} pages")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["render", "verify"])
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--baseurl", default="")
    args = parser.parse_args()
    if args.command == "render":
        render(args.output, args.source, args.baseurl)
    else:
        verify(args.output, args.baseurl)
