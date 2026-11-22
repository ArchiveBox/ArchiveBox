"""Transport same-run native captures to the existing strict gallery renderer."""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
from importlib.metadata import version
from pathlib import Path

PUBLIC_LANES = {
    **{plugin: (plugin,) for plugin in ("git", "packageregistry", "papersdl", "staticfile", "ytdlp")},
    "cad": ("caddl",),
    "boards": ("drawio", "excalidraw", "tldraw"),
    "documents": ("calendar", "liteparse", "opendataloader", "podcast_archiver"),
    "parsers": ("parse_jsonl_urls", "parse_netscape_urls", "parse_rss_urls", "sourcemaps"),
    "web": ("forumdl", "gallerydl"),
    "browser-automation": ("playwright", "puppeteer"),
}
PUBLIC_OWNERS = {plugin: lane for lane, plugins in PUBLIC_LANES.items() for plugin in plugins}
OPTIONAL_PROVIDER_VIEWS = {plugin: f"Snapshot View ({plugin})" for plugin in ("canva", "figma", "miro")}


def validate_provider_status(status):
    if (
        not isinstance(status, dict)
        or status.keys() != OPTIONAL_PROVIDER_VIEWS.keys()
        or any(value not in ("captured", "unavailable") for value in status.values())
    ):
        raise ValueError("Expected one explicit capture outcome per optional provider")
    return status


EXTRA_VIEWS = {"caddl": ("Model preview (STL)", "Model preview (3MF)", "Model preview (GLB)")}
PUBLIC_VIEWS = {
    lane: {name for plugin in plugins for name in (f"Snapshot View ({plugin})", *EXTRA_VIEWS.get(plugin, ()))}
    for lane, plugins in PUBLIC_LANES.items()
}
PROFILES = {"desktop": (1600, 1000), "tablet": (1024, 1366), "mobile": (390, 844)}
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def recipes(plan, split):
    moved = {lane: set() for lane in PUBLIC_LANES}
    protected = set()
    for example in plan["examples"]:
        names = set(example["plugins"])
        optional = names & OPTIONAL_PROVIDER_VIEWS.keys()
        if split and optional:
            if len(example["plugins"]) != 1:
                raise ValueError("An optional provider would split a native source across lanes")
            plugin = next(iter(optional))
            recipe = plan["overrides"][plugin]
            if plugin in protected or recipe["url"] != example["url"] or recipe.get("outputs"):
                raise ValueError(f"Optional provider is not an exact native singleton recipe: {plugin}")
            protected.add(plugin)
            continue
        known = names & PUBLIC_OWNERS.keys()
        if split and known:
            owners = {PUBLIC_OWNERS[name] for name in known}
            if len(owners) != 1 or names != known:
                raise ValueError("An anonymous recipe would split a native source across lanes")
            lane = owners.pop()
            url = example["url"]
            for name in known:
                recipe = plan["overrides"][name]
                views = [f"Snapshot View ({name})"] if url == recipe["url"] else []
                views.extend(output["name"] for output in recipe.get("outputs", ()) if output.get("url", recipe["url"]) == url)
                if moved[lane].intersection(views):
                    raise ValueError(f"Anonymous lane captures a view more than once: {lane}")
                moved[lane].update(views)
            continue
        yield ",".join(example["plugins"]) + "|" + example["url"]
    if split and moved != PUBLIC_VIEWS:
        raise ValueError("Anonymous recipe partition no longer covers the exact public gallery views")
    if split and protected != OPTIONAL_PROVIDER_VIEWS.keys():
        raise ValueError("Protected recipe partition no longer covers the exact optional gallery views")


def identity():
    return {
        **{key: os.environ[key] for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")},
        "pins": {package: version(package) for package in ("abx-plugins", "abx-dl", "abxpkg", "abxbus")},
    }


def read_rows(manifest):
    return [json.loads(line) for line in manifest.read_text().splitlines()]


def validate(lane, rows, root, digests):
    filenames = set()
    views = {}
    for row in rows:
        name, profile, filename = (row[key] for key in ("name", "profile", "filename"))
        if profile not in PROFILES or not re.fullmatch(r"[a-z0-9-]+\.png", filename) or not filename.endswith(f"-{profile}.png"):
            raise ValueError(f"Invalid capture filename or profile: {filename}")
        if filename in filenames or profile in views.setdefault(name, set()):
            raise ValueError(f"Duplicate capture: {filename}")
        views[name].add(profile)
        filenames.add(filename)
        image = root / filename
        if not image.is_file() or image.is_symlink():
            raise ValueError(f"Missing or invalid PNG file: {filename}")
        data = image.read_bytes()
        expected = PROFILES[profile]
        if (
            len(data) < 24
            or data[:8] != PNG_HEADER
            or struct.unpack(">II", data[16:24]) != expected
            or (row["width"], row["height"]) != expected
            or hashlib.sha256(data).hexdigest() != digests[filename]
        ):
            raise ValueError(f"Invalid capture dimensions or checksum: {filename}")
    if not views or filenames != digests.keys() or any(profiles != PROFILES.keys() for profiles in views.values()):
        raise ValueError(f"Incomplete viewport manifest: {lane}")
    if lane == "base":
        if views.keys() & set().union(*PUBLIC_VIEWS.values()):
            raise ValueError("Public recipe view was captured twice")
    elif lane in OPTIONAL_PROVIDER_VIEWS:
        if views.keys() != {OPTIONAL_PROVIDER_VIEWS[lane]}:
            raise ValueError(f"Optional provider did not capture its exact view: {lane}")
    elif views.keys() != PUBLIC_VIEWS[lane]:
        raise ValueError(f"Public lane did not capture its exact view: {lane}")


def pack(lane, manifest, screenshot_root, bundle):
    build = json.loads((screenshot_root / "build.json").read_text())
    current = identity()
    if build["revision"] != current["GITHUB_SHA"] or build["capture_count"] != len(build["files"]):
        raise ValueError("Native build differs from checked-out source or is incomplete")
    rows = read_rows(manifest)
    validate(lane, rows, screenshot_root, build["files"])
    bundle.mkdir()
    for name in build["files"]:
        shutil.copyfile(screenshot_root / name, bundle / name)
    shutil.copyfile(manifest, bundle / "capture.jsonl")
    receipt = {"identity": current, "lane": lane, "files": build["files"]}
    (bundle / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def merge(artifact_root, output, manifest, provider_status_out=None):
    current = identity()
    attempt = current["GITHUB_RUN_ATTEMPT"]
    lanes = ("base", *PUBLIC_LANES)
    bundles = {lane: artifact_root / f"gallery-capture-{attempt}-{lane}" for lane in lanes}
    expected_names = {bundle.name for bundle in bundles.values()}
    protected = artifact_root / f"gallery-capture-{attempt}-protected-providers"
    if provider_status_out is not None:
        expected_names.add(protected.name)
    if {path.name for path in artifact_root.iterdir()} != expected_names:
        raise ValueError("Unexpected or missing capture artifacts")
    if provider_status_out is not None:
        report = json.loads((protected / "status.json").read_text())
        if report["identity"] != current:
            raise ValueError("Mixed optional provider provenance")
        status = validate_provider_status(report["status"])
        captured = {provider for provider, state in status.items() if state == "captured"}
        if {path.name for path in protected.iterdir()} != captured | {"status.json"}:
            raise ValueError("Optional provider artifacts disagree with recorded outcomes")
        bundles.update((provider, protected / provider) for provider in sorted(captured))
    all_files = {}
    all_rows = []
    for lane, bundle in bundles.items():
        receipt = json.loads((bundle / "receipt.json").read_text())
        if receipt["identity"] != current or receipt["lane"] != lane:
            raise ValueError(f"Mixed capture provenance: {lane}")
        files = receipt["files"]
        rows = read_rows(bundle / "capture.jsonl")
        validate(lane, rows, bundle, files)
        if lane == "base" and provider_status_out is not None and any(row["name"] in OPTIONAL_PROVIDER_VIEWS.values() for row in rows):
            raise ValueError("Optional provider view was captured in the required base")
        if all_files.keys() & files.keys():
            raise ValueError(f"Duplicate gallery file: {lane}")
        all_files.update({name: bundle / name for name in files})
        all_rows.extend(rows)
    output.mkdir()
    for name, source in all_files.items():
        shutil.copyfile(source, output / name)
    manifest.write_text("".join(json.dumps(row) + "\n" for row in all_rows))
    if provider_status_out is not None:
        provider_status_out.write_text(json.dumps(status, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recipe_parser = commands.add_parser("recipes")
    recipe_parser.add_argument("plan", type=Path)
    recipe_parser.add_argument("split", choices=("0", "1"))
    pack_parser = commands.add_parser("pack")
    pack_parser.add_argument("lane", choices=("base", *PUBLIC_LANES, *OPTIONAL_PROVIDER_VIEWS))
    pack_parser.add_argument("manifest", type=Path)
    pack_parser.add_argument("screenshot_root", type=Path)
    pack_parser.add_argument("bundle", type=Path)
    merge_parser = commands.add_parser("merge")
    merge_parser.add_argument("artifacts", type=Path)
    merge_parser.add_argument("output", type=Path)
    merge_parser.add_argument("manifest", type=Path)
    merge_parser.add_argument("--provider-status-out", type=Path)
    args = parser.parse_args()
    if args.command == "recipes":
        print(*recipes(json.loads(args.plan.read_text()), args.split == "1"), sep="\n")
    elif args.command == "pack":
        pack(args.lane, args.manifest, args.screenshot_root, args.bundle)
    else:
        merge(args.artifacts, args.output, args.manifest, args.provider_status_out)


if __name__ == "__main__":
    main()
