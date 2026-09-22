#!/usr/bin/env python3

__package__ = "archivebox.cli"
__command__ = "archivebox oneshot"

import subprocess
import sys
from pathlib import Path

import rich_click as click

from archivebox.config import CONSTANTS
from archivebox.config.common import get_config


@click.command(add_help_option=False, context_settings=dict(ignore_unknown_options=True))
@click.argument("args", nargs=-1)
def main(args: tuple[str, ...] = ()) -> None:
    """Download URLs using abx-dl"""
    from archivebox.misc.checks import check_not_inside_source_dir

    check_not_inside_source_dir()

    cwd = Path.cwd()
    if any((path / CONSTANTS.SQL_INDEX_FILENAME).exists() for path in (cwd, *cwd.parents)):
        raise click.ClickException(
            "Refusing to run `archivebox oneshot` inside an ArchiveBox DATA_DIR. Use `archivebox add` here, or run oneshot from another directory.",
        )
    abxpkg_binary = Path(sys.executable).with_name("abxpkg")
    if not abxpkg_binary.is_file():
        raise click.ClickException(f"abxpkg executable is missing from the ArchiveBox environment: {abxpkg_binary}")
    abxpkg_lib_dir = get_config(include_machine=False).ABXPKG_LIB_DIR
    raise SystemExit(
        subprocess.run(
            [
                str(abxpkg_binary),
                f"--lib={abxpkg_lib_dir}",
                "--binproviders=env",
                "--install",
                "run",
                "abx-dl",
                *args,
            ],
        ).returncode,
    )


if __name__ == "__main__":
    main()
