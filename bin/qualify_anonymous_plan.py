"""Preflight the next anonymous gallery timing pilot against the installed native plan."""

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

LANES = {
    "cad": ("caddl",),
    "boards": ("drawio", "excalidraw", "tldraw"),
    "documents": ("calendar", "liteparse", "opendataloader", "podcast_archiver"),
    "parsers": ("parse_jsonl_urls", "parse_netscape_urls", "parse_rss_urls", "sourcemaps"),
    "web": ("forumdl", "gallerydl"),
}
EXTRA_VIEWS = {"caddl": ("Model preview (STL)", "Model preview (3MF)", "Model preview (GLB)")}
# Deliberately explicit for this pinned pilot. Failing at preflight avoids
# starting an unreviewed visit if the package changes its gallery inputs.
EXPECTED_VISITS = {"cad": 3, "boards": 3, "documents": 3, "parsers": 4, "web": 2}
REVIEWED_SERIAL_PROJECTION = "dcb5f6441ddf88ac2fba7b869c89911de0c83e87e8bae4e431bf7d27c5c90afd"
PROFILES = ("desktop", "tablet", "mobile")


def expected_native_row(plan, row):
    url, plugins = row["url"], row["plugins"]
    names = []
    for plugin in plugins:
        recipe = plan["overrides"][plugin]
        if recipe["url"] == url:
            names.append(f"Snapshot View ({plugin})")
        names.extend(output["name"] for output in recipe.get("outputs", []) if output.get("url", recipe["url"]) == url)
    return names


def qualify(full, selected):
    """Verify exact equality of serial and per-lane native source/view cover."""
    plugins = {plugin for group in LANES.values() for plugin in group}
    owners = {plugin: lane for lane, group in LANES.items() for plugin in group}
    if selected.keys() != {*LANES, "serial"} or len(plugins) != sum(map(len, LANES.values())):
        raise ValueError("Pilot manifest does not match the reviewed lane partition")

    identities = {}
    per_lane_rows = {lane: [] for lane in LANES}
    serial_rows = []
    for row in full["examples"]:
        row_plugins = set(row["plugins"])
        if not row_plugins & plugins:
            continue
        if row_plugins - plugins or len({owners[plugin] for plugin in row_plugins}) != 1:
            raise ValueError("A native recipe straddles or shares a non-pilot source")
        parsed = urlsplit(row["url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None:
            raise ValueError("The native plan contains a source outside the HTTPS pilot contract")
        lane = owners[next(iter(row_plugins))]
        if identities.setdefault(parsed.hostname.lower(), lane) != lane:
            raise ValueError("One exact source hostname would be visited by parallel pilot lanes")
        per_lane_rows[lane].append(row)
        serial_rows.append(row)

    evidence = {}
    for lane, captures in {**per_lane_rows, "serial": serial_rows}.items():
        native = selected[lane]
        lane_plugins = plugins if lane == "serial" else set(LANES[lane])
        expected_views = [view for plugin in sorted(lane_plugins) for view in (f"Snapshot View ({plugin})", *EXTRA_VIEWS.get(plugin, ()))]
        if native["examples"] != captures or native["overrides"].keys() != lane_plugins:
            raise ValueError(f"Native selected visits differ from full gallery plan in {lane}")
        if len(captures) != (sum(EXPECTED_VISITS.values()) if lane == "serial" else EXPECTED_VISITS[lane]):
            raise ValueError(f"Number of reviewed external source visits changed for {lane}")
        if native["importer_views"] or native["config_views"] or Counter(native["required"]) != Counter(expected_views):
            raise ValueError(f"Policy or required view coverage changed for {lane}")
        if Counter(view for row in captures for view in expected_native_row(full, row)) != Counter(expected_views):
            raise ValueError(f"Visit-to-view cover is not exact in {lane}")
        if any(native["overrides"][p] != full["overrides"][p] or native["overrides"][p].get("output_plugin", p) != p for p in lane_plugins):
            raise ValueError(f"Output provider or native configuration changed in {lane}")
        slugs = {re.sub(r"[^a-z0-9]+", "-", view.lower()).strip("-") for view in expected_views}
        if len(slugs) != len(expected_views):
            raise ValueError(f"Native filename collision in {lane}")
        # Store hashes, names, and counts, never raw source links.
        evidence[lane] = {
            "visits": len(captures),
            "source_projection_sha256": hashlib.sha256(
                json.dumps({"examples": captures, "overrides": native["overrides"]}, sort_keys=True).encode()
            ).hexdigest(),
            "files": sorted(f"{slug}-{profile}.png" for slug in slugs for profile in PROFILES),
        }
    if Counter(name for lane in LANES for name in evidence[lane]["files"]) != Counter(evidence["serial"]["files"]):
        raise ValueError("Pilot does not have exact PNG ownership")
    if evidence["serial"]["source_projection_sha256"] != REVIEWED_SERIAL_PROJECTION:
        raise ValueError("The pinned source or renderer configuration no longer matches the reviewed pilot")
    return evidence


def main(args):
    directory = Path(args[1])

    def read_plan(name):
        return json.loads((directory / f"{name}.json").read_text())

    print(json.dumps(qualify(read_plan("full"), {name: read_plan(name) for name in ("serial", *LANES)}), indent=2))


if __name__ == "__main__":
    main(sys.argv)
