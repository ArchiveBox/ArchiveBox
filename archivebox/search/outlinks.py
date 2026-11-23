"""Read crawl discovery outputs in a cancellable process (archive mounts can stall)."""

import json
import os
import stat
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path

from archivebox.plugins.url_outputs import parse_url_output, url_output_candidates


@contextmanager
def snapshot_directory(root, candidates):
    # Resolve historical UUID and timestamp layouts inside the cancellable
    # reader. Open relative to directory FDs so paths cannot escape the archive.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    for candidate in candidates:
        path = Path(candidate)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Snapshot must be inside the archive")
        with ExitStack() as handles:
            try:
                fd = os.open(root, flags)
                handles.callback(os.close, fd)
                for part in path.parts:
                    fd = os.open(part, flags, dir_fd=fd)
                    handles.callback(os.close, fd)
            except FileNotFoundError:
                continue
            yield fd
            return
    raise FileNotFoundError("Snapshot directory is unavailable")


def read_links(root, snapshot, byte_limit, file_limit, streaming=False):
    links = set()
    complete, observed = True, False
    usage = {"bytes": 0, "files": 0}
    directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        with snapshot_directory(root, snapshot) as fd:
            for relative in url_output_candidates(fd):
                plugin = relative.parent.name
                try:
                    with ExitStack() as output:
                        plugin_fd = os.open(plugin, directory, dir_fd=fd)
                        output.callback(os.close, plugin_fd)
                        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                        stream = output.enter_context(os.fdopen(os.open(relative.name, flags, dir_fd=plugin_fd), "rb"))
                        info = os.fstat(stream.fileno())
                        if not stat.S_ISREG(info.st_mode):
                            complete = False
                            continue
                        if not streaming and (usage["files"] >= file_limit or usage["bytes"] >= byte_limit):
                            complete = False
                            break
                        observed = True
                        usage["files"] += 1
                        if streaming:
                            # Pace large files and report liveness while keeping the same cursor.
                            heartbeat = start = time.monotonic()
                            total = 0
                            lines = iter(lambda: stream.readline((4 << 20) + 1), b"")
                        else:
                            data = stream.read(min(512 << 10, byte_limit - usage["bytes"]))
                            usage["bytes"] += len(data)
                            if info.st_size > len(data):
                                complete = False
                                data = data[: data.rfind(b"\n") + 1]
                            lines = data.splitlines()
                        for line in lines:
                            if streaming:
                                if len(line) > 4 << 20:
                                    raise ValueError("Outlink record exceeds 4 MiB")
                                total += len(line)
                                if time.monotonic() - heartbeat >= 2:
                                    print(json.dumps({"progress": True}), flush=True)
                                    heartbeat = time.monotonic()
                                if total >= 4 << 20:
                                    time.sleep(max(0, start + 1 - time.monotonic()))
                                    start, total = time.monotonic(), 0
                            try:
                                record = parse_url_output(line.decode("utf-8"), plugin)
                            except UnicodeError:
                                record = None
                            if record is None:
                                complete = False
                            elif record["url"].lower().startswith(("http://", "https://")):
                                if streaming:
                                    print(json.dumps(record["url"]))
                                else:
                                    links.add(record["url"])
                except FileNotFoundError:
                    # Most plugins produce other kinds of files.
                    continue
                except OSError:
                    complete = False
    except OSError:
        complete = False
    return {"links": sorted(links), "complete": observed and complete, "usage": usage}


if __name__ == "__main__":
    request = json.load(sys.stdin)
    if "snapshots" in request:
        for snapshot in request["snapshots"]:
            result = read_links(request["root"], snapshot, 0, 0, streaming=True)
            print(json.dumps({"complete": result["complete"]}), flush=True)
    else:
        json.dump(read_links(**request), sys.stdout)
