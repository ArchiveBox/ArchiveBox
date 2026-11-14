from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pdm.backend.hooks import Context


def pdm_build_initialize(context: Context) -> None:
    """Make the package description's setup link absolute and release-specific."""
    metadata = context.config.metadata
    readme = metadata["readme"]
    # PDM serializes the inline description into an sdist's pyproject.toml.
    text = (context.root / readme).read_text(encoding="utf-8") if isinstance(readme, str) else readme["text"]
    metadata["readme"] = {
        "text": text.replace(
            "](archivebox/auth/README.md)",
            f"](https://github.com/ArchiveBox/ArchiveBox/blob/v{metadata['version']}/archivebox/auth/README.md)",
        ),
        "content-type": "text/markdown",
    }


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
