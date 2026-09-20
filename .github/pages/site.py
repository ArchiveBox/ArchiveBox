"""Assemble and verify this repository's static Pages site (standard library only)."""

import argparse
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def replace_block(text, name, content):
    start, end = f"<!-- ARCHIVEBOX:{name} -->", f"<!-- /ARCHIVEBOX:{name} -->"
    pattern = re.escape(start) + r".*?" + re.escape(end)
    if re.search(pattern, text, re.DOTALL):
        return re.sub(pattern, lambda _: f"{start}\n{content}\n{end}", text, count=1, flags=re.DOTALL)
    if text.count(start) != 1:
        raise ValueError(f"Expected one {name} placeholder")
    return text.replace(start, f"{start}\n{content}\n{end}", 1)


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
    for name in ["chrome.css", "chrome.js"]:
        shutil.copyfile(HERE / "base" / name, assets / name)
    for name in config["pages"]:
        page = output / name
        text = page.read_text()
        base = "../" * (len(Path(name).parts) - 1) or "./"
        header = (HERE / "base/header.html").read_text().replace("__SITE_NAME__", escape(config["name"]))
        header = header.replace("__SITE_NAV__", (HERE / "nav.html").read_text().strip())
        text = replace_block(text, "HEADER", header)
        for kind in ["FOOTER-START", "FOOTER-END"]:
            text = replace_block(text, kind, (HERE / "base" / f"{kind.lower()}.html").read_text().strip())
        text = text.replace("__SITE_BASE__", base).replace("__SITE_REVISION__", revision)
        resources = f'<link rel="stylesheet" href="{base}site-base/chrome.css?v={revision}">\n<script src="{base}site-base/chrome.js?v={revision}" defer></script>'
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
        self.resources = []
        self.headers = self.footers = self.canonicals = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
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
