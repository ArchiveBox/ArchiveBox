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

PUBLIC_RECIPES = ("git", "packageregistry", "papersdl", "staticfile", "ytdlp")
PROFILES = {"desktop": (1600, 1000), "tablet": (1024, 1366), "mobile": (390, 844)}
PUBLIC_VIEWS = {plugin: f"Snapshot View ({plugin})" for plugin in PUBLIC_RECIPES}
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def recipes(plan, split):
    expected_public = set(PUBLIC_RECIPES)
    skipped = set()
    for example in plan["examples"]:
        names = set(example["plugins"])
        matched = names & expected_public
        if split and matched:
            if len(names) != 1 or matched & skipped:
                raise ValueError("Public recipe no longer owns one independent source")
            skipped.update(matched)
            continue
        yield ",".join(example["plugins"]) + "|" + example["url"]
    if split and skipped != expected_public:
        raise ValueError("Missing independent public recipes")


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
        if views.keys() & PUBLIC_VIEWS.values():
            raise ValueError("Public recipe view was captured twice")
    elif views.keys() != {PUBLIC_VIEWS[lane]}:
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


def merge(artifact_root, output, manifest):
    current = identity()
    attempt = current["GITHUB_RUN_ATTEMPT"]
    lanes = ("base", *PUBLIC_RECIPES)
    expected_names = {f"gallery-capture-{attempt}-{lane}" for lane in lanes}
    if {path.name for path in artifact_root.iterdir()} != expected_names:
        raise ValueError("Unexpected or missing capture artifacts")
    all_files = {}
    all_rows = []
    for lane in lanes:
        bundle = artifact_root / f"gallery-capture-{attempt}-{lane}"
        receipt = json.loads((bundle / "receipt.json").read_text())
        if receipt["identity"] != current or receipt["lane"] != lane:
            raise ValueError(f"Mixed capture provenance: {lane}")
        files = receipt["files"]
        rows = read_rows(bundle / "capture.jsonl")
        validate(lane, rows, bundle, files)
        if all_files.keys() & files.keys():
            raise ValueError(f"Duplicate gallery file: {lane}")
        all_files.update({name: bundle / name for name in files})
        all_rows.extend(rows)
    output.mkdir()
    for name, source in all_files.items():
        shutil.copyfile(source, output / name)
    manifest.write_text("".join(json.dumps(row) + "\n" for row in all_rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recipe_parser = commands.add_parser("recipes")
    recipe_parser.add_argument("plan", type=Path)
    recipe_parser.add_argument("split", choices=("0", "1"))
    pack_parser = commands.add_parser("pack")
    pack_parser.add_argument("lane", choices=("base", *PUBLIC_RECIPES))
    pack_parser.add_argument("manifest", type=Path)
    pack_parser.add_argument("screenshot_root", type=Path)
    pack_parser.add_argument("bundle", type=Path)
    merge_parser = commands.add_parser("merge")
    merge_parser.add_argument("artifacts", type=Path)
    merge_parser.add_argument("output", type=Path)
    merge_parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.command == "recipes":
        print(*recipes(json.loads(args.plan.read_text()), args.split == "1"), sep="\n")
    elif args.command == "pack":
        pack(args.lane, args.manifest, args.screenshot_root, args.bundle)
    else:
        merge(args.artifacts, args.output, args.manifest)


if __name__ == "__main__":
    main()
