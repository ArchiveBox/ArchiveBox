"""Read registered JSONL outlinks inside a short-lived, cancellable process.

Archive directories can be on a remote mount. A deadline checked between files
cannot interrupt a blocked open/read. The caller also bounds the process lifetime.
"""

import json
import os
import stat
import sys
import time
from contextlib import ExitStack
from pathlib import Path


def read_links(root, relatives, byte_limit, file_limit, streaming=False):
    links = set()
    complete, observed = True, False
    usage = {"bytes": 0, "files": 0}
    directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    for relative in relatives:
        if not streaming and (usage["files"] >= file_limit or usage["bytes"] >= byte_limit):
            complete = False
            break
        parts = Path(relative).parts
        if not parts or ".." in parts or Path(relative).is_absolute():
            raise ValueError("Outlinks must be inside the archive")
        usage["files"] += 1
        try:
            with ExitStack() as handles:
                fd = os.open(root, directory)
                handles.callback(os.close, fd)
                for part in parts[:-1]:
                    fd = os.open(part, directory, dir_fd=fd)
                    handles.callback(os.close, fd)
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                stream = handles.enter_context(os.fdopen(os.open(parts[-1], flags, dir_fd=fd), "rb"))
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    complete = False
                    continue
                observed = True
                if streaming:
                    # Keep the file open between windows. Do not restart at
                    # byte zero or buffer a whole outgoing-link manifest.
                    heartbeat = start = time.monotonic()
                    size = 0
                    # Bound a malformed record with no newline independently
                    # from the length of a valid many-record manifest.
                    while line := stream.readline((4 << 20) + 1):
                        if len(line) > 4 << 20:
                            raise ValueError("Outlink record exceeds 4 MiB")
                        size += len(line)
                        if time.monotonic() - heartbeat >= 2:
                            print(json.dumps({"progress": True}), flush=True)
                            heartbeat = time.monotonic()
                        if size >= 4 << 20:
                            time.sleep(max(0, start + 1 - time.monotonic()))
                            start, size = time.monotonic(), 0
                        try:
                            url = json.loads(line).get("url")
                        except (AttributeError, ValueError):
                            complete = False
                            continue
                        if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
                            print(json.dumps(url))
                    continue
                data = stream.read(min(512 << 10, byte_limit - usage["bytes"]))
                usage["bytes"] += len(data)
                if info.st_size > len(data):
                    complete = False
                    data = data[: data.rfind(b"\n") + 1]
                for line in data.splitlines():
                    try:
                        url = json.loads(line).get("url")
                    except (AttributeError, ValueError):
                        complete = False
                        continue
                    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
                        links.add(url)
        except FileNotFoundError:
            continue
        except OSError:
            complete = False
    return {"links": sorted(links), "complete": observed and complete, "usage": usage}


if __name__ == "__main__":
    json.dump(read_links(**json.load(sys.stdin)), sys.stdout)
