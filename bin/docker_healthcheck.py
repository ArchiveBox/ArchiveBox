"""Probe this collection's actual HTTP listener, including CLI bind overrides.

Docker healthchecks do not inherit environment changes made by the server.
Inspect only ArchiveBox HTTP workers, so IPv4/IPv6, custom ports, and debug
reloads use the address that is listening rather than the image's defaults.
"""

import os
import pwd
import socket
import sys
from http.client import HTTPConnection, HTTPException
from ipaddress import IPv6Address
from pathlib import Path

import psutil


def main() -> int:
    # Docker's default root lacks SYS_PTRACE, so it cannot inspect the
    # non-root worker's descriptors. Use the same account as the entrypoint.
    if os.geteuid() == 0:
        user = pwd.getpwnam(os.environ.get("ARCHIVEBOX_USER", "archivebox"))
        os.initgroups(user.pw_name, user.pw_gid)
        os.setgid(user.pw_gid)
        os.setuid(user.pw_uid)
    data_dir = Path(os.environ.get("DATA_DIR", "/data")).resolve()
    for process in psutil.process_iter(["cmdline", "cwd"]):
        command = process.info["cmdline"] or []
        production_worker = "archivebox.workers.http_server" in command or (
            "uvicorn" in command and "archivebox.core.asgi:application" in command
        )
        development_worker = any(
            Path(arg).name == "archivebox" and command[index + 1 : index + 3] == ["manage", "runserver"]
            for index, arg in enumerate(command)
        )
        if not (production_worker or development_worker) or not process.info["cwd"]:
            continue
        if Path(process.info["cwd"]).resolve() != data_dir:
            continue
        bind_host = ""
        for index, arg in enumerate(command):
            if arg.startswith("--host="):
                bind_host = arg.split("=", 1)[1]
            elif arg == "--host" and index + 1 < len(command):
                bind_host = command[index + 1]
            elif development_worker and arg.startswith("[") and "]:" in arg:
                bind_host = arg[1 : arg.index("]")]
        try:
            listeners = process.net_connections(kind="inet")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for listener in listeners:
            if listener.status != psutil.CONN_LISTEN or listener.family not in (socket.AF_INET, socket.AF_INET6):
                continue
            host, port = listener.laddr
            host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
            # Linux psutil omits IPv6 scope IDs from socket addresses. Restore
            # only this worker's explicitly bound interface, never guess one.
            if listener.family == socket.AF_INET6 and "%" in bind_host:
                if IPv6Address(host.split("%", 1)[0]) == IPv6Address(bind_host.split("%", 1)[0]):
                    host = bind_host
            # A zone selects the local interface; it is not part of HTTP Host.
            http_host = f"[{host.split('%', 1)[0]}]" if listener.family == socket.AF_INET6 else host
            connection = HTTPConnection(host, port, timeout=5)
            try:
                connection.request("GET", "/health/", headers={"Host": f"{http_host}:{port}"})
                response = connection.getresponse()
                if response.status == 200 and response.getheader("X-ArchiveBox-Health") == "OK" and response.read(16).strip() == b"OK":
                    print("OK")
                    return 0
            except (OSError, HTTPException):
                pass
            finally:
                connection.close()
    print("No healthy ArchiveBox HTTP listener for this collection", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
