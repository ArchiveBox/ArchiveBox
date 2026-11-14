from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pdm.backend.hooks import Context


def _current_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    commit_hash = result.stdout.strip()
    return commit_hash if re.fullmatch(r"[0-9a-f]{40}", commit_hash) else None


def pdm_build_update_files(context: Context, files: dict[str, Path]) -> None:
    commit_hash = _current_commit(context.root)
    if not commit_hash:
        return

    dst = context.ensure_build_dir() / "archivebox" / "COMMIT_SHA"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(f"{commit_hash}\n", encoding="utf-8")
    files["archivebox/COMMIT_SHA"] = dst
