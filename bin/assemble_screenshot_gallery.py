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
    **{plugin: (plugin,) for plugin in ("git", "packageregistry", "papersdl", "staticfile", "ytdlp", "iwork")},
    "cad": ("caddl",),
    "boards": ("drawio", "excalidraw", "tldraw"),
    "documents": ("calendar", "liteparse", "opendataloader", "podcast_archiver"),
    "parsers": ("parse_jsonl_urls", "parse_netscape_urls", "parse_rss_urls", "sourcemaps"),
    "web": ("forumdl", "gallerydl"),
    "browser-automation": ("playwright", "puppeteer"),
}
PUBLIC_OWNERS = {plugin: lane for lane, plugins in PUBLIC_LANES.items() for plugin in plugins}


def view_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def recipe_id(name, owner):
    return "recipe-" + hashlib.sha256(f"{owner}:{name}".encode()).hexdigest()[:16]


def recipe_status(outcomes, owners):
    return {recipe_id(name, owner): {"status": outcomes[name], "views": [view_slug(name)]} for name, owner in owners.items()}


def validate_recipe_status(status, owners):
    groups = {recipe_id(name, owner): name for name, owner in owners.items()}
    if len(groups) != len(owners) or len({view_slug(name) for name in owners}) != len(owners):
        raise ValueError("Plugin gallery plan has colliding ownership")
    if not isinstance(status, dict) or status.keys() != groups.keys():
        raise ValueError("Expected one explicit capture outcome per owned plugin view")
    outcomes = {}
    for key, name in groups.items():
        record = status[key]
        if (
            not isinstance(record, dict)
            or record.keys() != {"status", "views"}
            or record["status"] not in ("captured", "unavailable")
            or record["views"] != [view_slug(name)]
        ):
            raise ValueError(f"Invalid owned plugin outcome: {name}")
        outcomes[name] = record["status"]
    return outcomes


EXTRA_VIEWS = {"caddl": ("Model preview (STL)", "Model preview (3MF)", "Model preview (GLB)")}
PUBLIC_VIEWS = {
    lane: {name for plugin in plugins for name in (f"Snapshot View ({plugin})", *EXTRA_VIEWS.get(plugin, ()))}
    for lane, plugins in PUBLIC_LANES.items()
}
PROFILES = {"desktop": (1600, 1000), "tablet": (1024, 1366), "mobile": (390, 844)}
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def recipes(plan, split):
    moved = {lane: set() for lane in PUBLIC_LANES}
    for example in plan["examples"]:
        names = set(example["plugins"])
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


def identity():
    return {
        **{key: os.environ[key] for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")},
        "pins": {package: version(package) for package in ("abx-plugins", "abx-dl", "abxpkg", "abxbus")},
    }


def read_rows(manifest):
    return [json.loads(line) for line in manifest.read_text().splitlines()]


def plan_owners(lane):
    from generate_ui_screenshot_gallery import plugin_screenshot_plan

    owners = plugin_screenshot_plan()["owned_views"]
    return {name: plugin for name, plugin in owners.items() if lane == "whole" or PUBLIC_OWNERS.get(plugin, "base") == lane}


def validate(lane, rows, root, digests, outcomes=None):
    filenames = set()
    views = {}
    for row in rows:
        name, profile, filename = (row[key] for key in ("name", "profile", "filename"))
        if profile not in PROFILES or not re.fullmatch(r"[a-z0-9-]+\.png", filename) or filename != f"{view_slug(name)}-{profile}.png":
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
    if (
        (not views and (lane == "base" or outcomes is None))
        or filenames != digests.keys()
        or any(profiles != PROFILES.keys() for profiles in views.values())
    ):
        raise ValueError(f"Incomplete viewport manifest: {lane}")
    if outcomes is not None:
        owners = plan_owners(lane)
        actual = validate_recipe_status(outcomes, owners)
        if any((status == "captured") != (name in views) for name, status in actual.items()):
            raise ValueError(f"Capture disagrees with plugin view outcomes: {lane}")
    if lane == "base":
        if views.keys() & set().union(*PUBLIC_VIEWS.values()):
            raise ValueError("Public recipe view was captured twice")
    else:
        expected = PUBLIC_VIEWS[lane]
        if outcomes is not None:
            expected = expected - {name for name, status in actual.items() if status == "unavailable"}
        if views.keys() != expected:
            raise ValueError(f"Public lane did not capture its exact view: {lane}")


def collect_outcomes(lane, rows, unavailable):
    missing = unavailable.read_text().splitlines()
    names = {row["name"] for row in rows}
    owners = plan_owners(lane)
    if set(missing) - owners.keys() or len(missing) != len(set(missing)):
        raise ValueError(f"Unowned or duplicate failure in lane: {lane}")
    if set(missing) & names:
        raise ValueError(f"Unavailable plugin produced gallery images: {lane}")
    return recipe_status({name: "unavailable" if name in missing else "captured" for name in owners}, owners)


def pack(lane, manifest, screenshot_root, bundle, unavailable=None):
    build = json.loads((screenshot_root / "build.json").read_text())
    current = identity()
    if build["revision"] != current["GITHUB_SHA"] or build["capture_count"] != len(build["files"]):
        raise ValueError("Native build differs from checked-out source or is incomplete")
    rows = read_rows(manifest)
    outcomes = collect_outcomes(lane, rows, unavailable) if unavailable is not None else None
    validate(lane, rows, screenshot_root, build["files"], outcomes)
    bundle.mkdir()
    for name in build["files"]:
        shutil.copyfile(screenshot_root / name, bundle / name)
    shutil.copyfile(manifest, bundle / "capture.jsonl")
    receipt = {"identity": current, "lane": lane, "files": build["files"]}
    if outcomes is not None:
        receipt["outcomes"] = outcomes
    (bundle / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def merge(artifact_root, output, manifest, recipe_outcomes_out=None):
    current = identity()
    attempt = current["GITHUB_RUN_ATTEMPT"]
    lanes = ("base", *PUBLIC_LANES)
    bundles = {lane: artifact_root / f"gallery-capture-{attempt}-{lane}" for lane in lanes}
    expected_names = {bundle.name for bundle in bundles.values()}
    if {path.name for path in artifact_root.iterdir()} != expected_names:
        raise ValueError("Unexpected or missing capture artifacts")
    status = {}
    all_files = {}
    all_rows = []
    for lane, bundle in bundles.items():
        receipt = json.loads((bundle / "receipt.json").read_text())
        if receipt["identity"] != current or receipt["lane"] != lane:
            raise ValueError(f"Mixed capture provenance: {lane}")
        files = receipt["files"]
        rows = read_rows(bundle / "capture.jsonl")
        outcomes = receipt["outcomes"] if recipe_outcomes_out is not None else None
        validate(lane, rows, bundle, files, outcomes)
        if {path.name for path in bundle.iterdir()} != files.keys() | {"capture.jsonl", "receipt.json"}:
            raise ValueError(f"Unexpected native capture files: {lane}")
        if outcomes is not None:
            if status.keys() & outcomes.keys():
                raise ValueError("Duplicate plugin outcomes")
            status.update(outcomes)
        if all_files.keys() & files.keys():
            raise ValueError(f"Duplicate gallery file: {lane}")
        all_files.update({name: bundle / name for name in files})
        all_rows.extend(rows)
    if recipe_outcomes_out is not None:
        from generate_ui_screenshot_gallery import plugin_screenshot_plan

        validate_recipe_status(status, plugin_screenshot_plan()["owned_views"])
    output.mkdir()
    for name, source in all_files.items():
        shutil.copyfile(source, output / name)
    manifest.write_text("".join(json.dumps(row) + "\n" for row in all_rows))
    if recipe_outcomes_out is not None:
        recipe_outcomes_out.write_text(json.dumps(status, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recipe_parser = commands.add_parser("recipes")
    recipe_parser.add_argument("plan", type=Path)
    recipe_parser.add_argument("split", choices=("0", "1"))
    pack_parser = commands.add_parser("pack")
    pack_parser.add_argument("lane", choices=("base", *PUBLIC_LANES))
    pack_parser.add_argument("manifest", type=Path)
    pack_parser.add_argument("screenshot_root", type=Path)
    pack_parser.add_argument("bundle", type=Path)
    pack_parser.add_argument("--unavailable", type=Path)
    merge_parser = commands.add_parser("merge")
    merge_parser.add_argument("artifacts", type=Path)
    merge_parser.add_argument("output", type=Path)
    merge_parser.add_argument("manifest", type=Path)
    merge_parser.add_argument("--recipe-outcomes-out", type=Path)
    whole_parser = commands.add_parser("whole-outcomes")
    whole_parser.add_argument("manifest", type=Path)
    whole_parser.add_argument("unavailable", type=Path)
    whole_parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "recipes":
        print(*recipes(json.loads(args.plan.read_text()), args.split == "1"), sep="\n")
    elif args.command == "pack":
        pack(args.lane, args.manifest, args.screenshot_root, args.bundle, args.unavailable)
    elif args.command == "merge":
        merge(args.artifacts, args.output, args.manifest, args.recipe_outcomes_out)
    else:
        outcomes = collect_outcomes("whole", read_rows(args.manifest), args.unavailable)
        args.output.write_text(json.dumps(outcomes, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
