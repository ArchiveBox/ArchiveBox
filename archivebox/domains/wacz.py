"""Package existing recordings using Webrecorder's nested WACZ format.

This is the same ``multi-wacz-package`` profile emitted by Browsertrix:
https://github.com/webrecorder/browsertrix/blob/main/backend/btrixcloud/storages.py
ReplayWeb.page resolves URLs across the children without changing their WARCs,
indexes, signatures, or recorded response bytes.
"""

import hashlib
import json
import os
import struct
import time
import zipfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO


def write_site_wacz(
    output: BinaryIO,
    recordings: Iterable[Path],
    *,
    title: str,
    main_url: str,
    progress: Callable[[dict], None] | None = None,
) -> int:
    """Write one portable WACZ and return its recording count.

    The caller selects recordings from the authorized snapshots. Only existing,
    finalized WACZ files are accepted; a missing recording is never synthesized
    from HTML. Sources are streamed into stored ZIP members so replay can use
    byte ranges, with memory bounded independently of archive size.
    """
    paths = list(dict.fromkeys(Path(path).resolve() for path in recordings))
    if not paths:
        raise ValueError("No WACZ recordings are available. Capture pages with a WACZ recorder enabled first.")
    total_bytes = sum(path.stat().st_size for path in paths)
    copied_bytes = 0
    reported_at = 0.0
    resources = []

    def report(completed: int, force: bool = False):
        nonlocal reported_at
        now = time.monotonic()
        if progress is not None and (force or now - reported_at >= 1):
            progress({"bytes": copied_bytes, "total_bytes": total_bytes, "recordings": completed, "total_recordings": len(paths)})
            reported_at = now

    report(0, force=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
        for index, path in enumerate(paths):
            # Check the central directory and metadata before including a file.
            # Opening the same file for validation and copying also avoids a
            # recorder replacing the pathname between those two operations.
            with path.open("rb") as source:
                with zipfile.ZipFile(source) as recording:
                    package = json.loads(recording.read("datapackage.json"))
                    if not package.get("resources"):
                        raise ValueError(f"WACZ has no recorded resources: {path.name}")
                source.seek(0)
                name = f"recordings/{index:06d}.wacz"
                digest = hashlib.sha256()
                size = 0
                # Supply the known size so zipfile chooses ZIP64 only when
                # needed. Forced ZIP64 on a small member adds a local-header
                # extra field absent from its central directory; wabac's
                # range-reader then calculates the wrong nested ZIP offset.
                info = zipfile.ZipInfo(name)
                source_stat = os.fstat(source.fileno())
                info.file_size = source_stat.st_size
                # Standard extended modification time also keeps a central
                # extra field at zipfile's conservative ZIP64 size boundary,
                # where a local ZIP64 field may precede a 32-bit central size.
                info.extra = struct.pack("<HHBI", 0x5455, 5, 1, max(0, min(int(source_stat.st_mtime), 0xFFFFFFFF)))
                with bundle.open(info, "w") as member:
                    while chunk := source.read(1024 * 1024):
                        member.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                        copied_bytes += len(chunk)
                        report(index)
                resources.append({"name": name, "path": name, "hash": f"sha256:{digest.hexdigest()}", "bytes": size})
                report(index + 1, force=True)

        package_bytes = json.dumps(
            {
                "profile": "multi-wacz-package",
                "title": title,
                "mainPageUrl": main_url,
                "created": datetime.now(UTC).isoformat(),
                "software": "ArchiveBox",
                "resources": resources,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        bundle.writestr("datapackage.json", package_bytes)
        bundle.writestr(
            "datapackage-digest.json",
            json.dumps({"path": "datapackage.json", "hash": f"sha256:{hashlib.sha256(package_bytes).hexdigest()}"}),
        )
    return len(resources)


def replay_assets(config, format="wacz", *, provider=None) -> dict[str, bytes]:
    """Export the installed replay player, using the normal plugin asset hook."""
    from django.http import HttpResponse

    from archivebox.plugins.discovery import get_replay_asset_bundle, serve_plugin_replay_asset

    provider, paths = get_replay_asset_bundle(format, provider=provider)
    assets = {}
    for path in paths:
        response = serve_plugin_replay_asset(path, config, HttpResponse, provider=provider)
        if response is None:
            raise ValueError(f"Replay asset provider {provider} cannot serve {path}")
        try:
            if response.status_code != 200:
                raise ValueError(f"Replay asset provider {provider} returned {response.status_code} for {path}")
            assets[path] = b"".join(response.streaming_content) if response.streaming else response.content
        finally:
            response.close()
    return assets
