"""Official rclone binary installation invoked through abxpkg's BashProvider."""

import hashlib
import io
import os
from pathlib import Path
import platform
import sys
from urllib.request import Request, urlopen
import zipfile

from abxpkg import BashProvider, BinProvider

VERSION = "1.74.2"


class OfficialRcloneProvider(BashProvider):
    """Only reuse this managed build; Homebrew's macOS binary cannot mount."""

    def default_abspath_handler(self, bin_name, **context):
        return BinProvider.default_abspath_handler(self, bin_name, **context)


def install_official(target: Path) -> None:
    system = {"Darwin": "osx", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64", "AMD64": "amd64"}.get(platform.machine())
    if not system or not arch:
        raise RuntimeError("Managed archive mounts currently require macOS or Linux on arm64 or amd64.")
    name = f"rclone-v{VERSION}-{system}-{arch}"
    base = f"https://downloads.rclone.org/v{VERSION}"
    headers = {"User-Agent": "ArchiveBox storage installer"}
    with urlopen(Request(f"{base}/SHA256SUMS", headers=headers), timeout=60) as response:
        checksums = response.read().decode()
    expected = next(
        parts[0] for line in checksums.splitlines() if len(parts := line.split()) == 2 and parts[-1].lstrip("*") == f"{name}.zip"
    )
    with urlopen(Request(f"{base}/{name}.zip", headers=headers), timeout=120) as response:
        body = response.read()
    if hashlib.sha256(body).hexdigest() != expected.lower():
        raise RuntimeError("Official rclone download failed its SHA-256 verification.")
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        binary = archive.read(f"{name}/rclone")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_bytes(binary)
    temporary.chmod(0o755)
    temporary.replace(target)


if __name__ == "__main__":
    install_official(Path(sys.argv[1]))
