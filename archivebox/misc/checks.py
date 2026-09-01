__package__ = "archivebox.misc"

import os
import signal
import sys
import time
import threading
from contextlib import contextmanager
from pathlib import Path

from rich import print
from rich.panel import Panel

# DO NOT ADD ANY TOP-LEVEL IMPORTS HERE to anything other than builtin python libraries
# this file is imported by archivebox/__init__.py
# and any imports here will be imported by EVERYTHING else
# so this file should only be used for pure python checks
# that don't need to import other parts of ArchiveBox

# if a check needs to import other parts of ArchiveBox,
# the imports should be done inside the check function
# and you should make sure if you need to import any django stuff
# that the check is called after django.setup() has been called


def _migration_interrupt_message(*, before_apply: bool = False) -> str:
    status = "Migration cancelled before any changes were applied." if before_apply else "Migration interrupted."
    return (
        f"\n[X] {status}\n"
        "    Database migrations are atomic; interrupted migration work is rolled back or left unapplied,\n"
        "    so no partially-applied migration is recorded and no data loss has occurred.\n\n"
        "    To continue the upgrade, run:\n"
        "        archivebox init\n"
    )


@contextmanager
def _exit_on_migration_interrupt():
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    handled_signals = (signal.SIGINT, signal.SIGTERM)
    previous_handlers = {sig: signal.getsignal(sig) for sig in handled_signals}

    def handle_shutdown(_signum, _frame):
        try:
            os.write(sys.stderr.fileno(), _migration_interrupt_message().encode())
        except Exception:
            pass
        # Django's migration executor can catch or delay normal exceptions while
        # unwinding transactions. Use the real process exit path after printing
        # the recovery command so Ctrl+C/SIGTERM during auto-migrations does not
        # leave `archivebox server` apparently hung after the user asked it to
        # stop. Migrations are atomic, so this does not record partial progress.
        os._exit(130)

    try:
        for sig in handled_signals:
            signal.signal(sig, handle_shutdown)
        yield
    finally:
        for sig, previous_handler in previous_handlers.items():
            signal.signal(sig, previous_handler)


def check_data_folder(config=None, **config_kwargs) -> None:
    from archivebox import DATA_DIR
    from archivebox.config import CONSTANTS
    from archivebox.config.common import get_config
    from archivebox.config.paths import create_and_chown_dir, get_or_create_working_tmp_dir, get_or_create_working_lib_dir

    config = config or get_config(**config_kwargs)
    archive_dir = CONSTANTS.ARCHIVE_DIR
    archive_dir_exists = os.path.isdir(archive_dir)
    if not archive_dir_exists:
        print("[red][X] No archivebox index found in the current directory.[/red]", file=sys.stderr)
        print(f"    {DATA_DIR}", file=sys.stderr)
        print(file=sys.stderr)
        print("    [violet]Hint[/violet]: Are you running archivebox in the right folder?", file=sys.stderr)
        print("        cd path/to/your/archive/folder", file=sys.stderr)
        print("        archivebox [command]", file=sys.stderr)
        print(file=sys.stderr)
        print("    [violet]Hint[/violet]: To create a new archive collection or import existing data in this folder, run:", file=sys.stderr)
        print("        archivebox init", file=sys.stderr)
        raise SystemExit(2)

    # Create data dir subdirs
    create_and_chown_dir(CONSTANTS.SOURCES_DIR)
    create_and_chown_dir(CONSTANTS.USERS_DIR)
    create_and_chown_dir(CONSTANTS.PERSONAS_DIR / "Default")
    create_and_chown_dir(CONSTANTS.LOGS_DIR)

    # Create /tmp and /lib dirs if they don't exist
    get_or_create_working_tmp_dir(autofix=True, quiet=False, config=config)
    get_or_create_working_lib_dir(autofix=True, quiet=False, config=config)

    # Check data dir permissions, /tmp, and /lib permissions
    check_data_dir_permissions(config=config)


def check_migrations(*, blocking: bool = True, auto_apply: bool = False, cancel_delay: int = 3) -> list[str]:
    from archivebox import DATA_DIR
    from archivebox.misc.db import apply_migrations, migration_state, pending_migrations

    pending, missing_from_code, rollback_targets = migration_state()
    is_migrating = any(arg in sys.argv for arg in ["makemigrations", "migrate", "init"]) or os.environ.get("ARCHIVEBOX_WANTS_INIT") == "1"

    if missing_from_code:
        print(
            "[red][X] This collection was migrated by a newer version of ArchiveBox than the one currently running.[/red]",
            file=sys.stderr,
        )
        print(f"    {DATA_DIR}", file=sys.stderr)
        print(file=sys.stderr)
        print("    [violet]Hint:[/violet] Upgrade ArchiveBox / pull the latest Docker image, then restart:", file=sys.stderr)
        print("        docker compose pull && docker compose up -d", file=sys.stderr)
        print(file=sys.stderr)
        print("    Applied migrations missing from this build:", file=sys.stderr)
        for migration in missing_from_code[:10]:
            print(f"        {migration}", file=sys.stderr)
        if len(missing_from_code) > 10:
            print(f"        ... and {len(missing_from_code) - 10} more", file=sys.stderr)
        print(file=sys.stderr)
        print(
            "    If you are intentionally trying to downgrade, switch back to the newer version temporarily",
            file=sys.stderr,
        )
        print(
            "    and run this to downgrade the DB version (back up your DB first!):",
            file=sys.stderr,
        )
        for app, target in sorted(rollback_targets.items()):
            print(f"        archivebox manage migrate {app} {target}", file=sys.stderr)
        raise SystemExit(3)

    if pending and not is_migrating:
        print("[red][X] This collection was created with an older version of ArchiveBox and must be upgraded first.[/red]", file=sys.stderr)
        print(f"    {DATA_DIR}", file=sys.stderr)
        print(file=sys.stderr)
        print(
            f"    [violet]Hint:[/violet] To upgrade it to the latest version and apply the {len(pending)} pending migrations, run:",
            file=sys.stderr,
        )
        print("        archivebox init", file=sys.stderr)
        if auto_apply:
            print(file=sys.stderr)
            print(
                f"[yellow][*] ArchiveBox will apply migrations automatically in {cancel_delay}s. Press CTRL+C to cancel.[/yellow]",
                file=sys.stderr,
            )
            try:
                time.sleep(cancel_delay)
            except KeyboardInterrupt:
                print(_migration_interrupt_message(before_apply=True), file=sys.stderr)
                raise SystemExit(130) from None

            # Always delegate to Django's migration executor. It records each
            # migration only after it succeeds, so power loss or SIGKILL leaves
            # unapplied work visible here and the next startup resumes normally.
            print("[yellow][*] Applying database migrations...[/yellow]", file=sys.stderr)
            try:
                with _exit_on_migration_interrupt():
                    apply_migrations(stdout=sys.stderr, stderr=sys.stderr, verbosity=1)
            except KeyboardInterrupt:
                print(_migration_interrupt_message(), file=sys.stderr)
                raise SystemExit(130) from None
            return pending_migrations()
        if blocking:
            raise SystemExit(3)
    return pending


def check_io_encoding():
    PYTHON_ENCODING = (sys.__stdout__ or sys.stdout or sys.__stderr__ or sys.stderr).encoding.upper().replace("UTF8", "UTF-8")

    if PYTHON_ENCODING != "UTF-8":
        print(
            f"[red][X] Your system is running python3 scripts with a bad locale setting: {PYTHON_ENCODING} (it should be UTF-8).[/red]",
            file=sys.stderr,
        )
        print('    To fix it, add the line "export PYTHONIOENCODING=UTF-8" to your ~/.bashrc file (without quotes)', file=sys.stderr)
        print('    Or if you\'re using ubuntu/debian, run "dpkg-reconfigure locales"', file=sys.stderr)
        print("")
        print("    Confirm that it's fixed by opening a new shell and running:", file=sys.stderr)
        print('        python3 -c "import sys; print(sys.stdout.encoding)"   # should output UTF-8', file=sys.stderr)
        raise SystemExit(2)


def check_not_root():
    is_getting_help = "-h" in sys.argv or "--help" in sys.argv or "help" in sys.argv
    is_getting_version = "--version" in sys.argv or "version" in sys.argv

    if os.geteuid() == 0 and not (is_getting_help or is_getting_version):
        print("[yellow][!] Running ArchiveBox as root is not recommended.[/yellow]", file=sys.stderr)
        print("    Root-owned DATA_DIR files may be inaccessible to non-root users later.", file=sys.stderr)
        print("        https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#do-not-run-as-root", file=sys.stderr)


def is_archivebox_source_root(path: Path | str | None = None) -> bool:
    """Return whether path is the root of an ArchiveBox source checkout."""
    path = Path(path or os.getcwd()).resolve()
    try:
        return (path / ".git").exists() and (path / "archivebox" / "__init__.py").is_file() and (path / "pyproject.toml").is_file()
    except OSError:
        return False


def check_not_inside_source_dir(path: Path | str | None = None) -> None:
    """Refuse data-producing execution from the ArchiveBox source checkout."""
    if is_archivebox_source_root(path):
        raise SystemExit(
            "[!] Refusing to use the ArchiveBox source checkout as a DATA_DIR. "
            "Create a separate data directory, cd into it, and run ArchiveBox there.",
        )


def check_data_dir_permissions(config=None, **config_kwargs):
    from archivebox import DATA_DIR
    from archivebox.misc.logging import STDERR
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP, DEFAULT_UID, DEFAULT_GID, IS_ROOT, USER
    from archivebox.config.paths import get_or_create_working_tmp_dir, get_or_create_working_lib_dir

    data_dir_stat = Path(DATA_DIR).stat()
    data_dir_uid, data_dir_gid = data_dir_stat.st_uid, data_dir_stat.st_gid
    data_owned_by_root = data_dir_uid == 0

    data_owner_doesnt_match = (data_dir_uid != ARCHIVEBOX_USER and data_dir_gid != ARCHIVEBOX_GROUP) if not IS_ROOT else False
    data_not_writable = not (os.path.isdir(DATA_DIR) and os.access(DATA_DIR, os.W_OK))
    if data_not_writable:
        STDERR.print(
            f"\n[yellow]:warning: Warning: ArchiveBox [blue]DATA_DIR[/blue] is not writable by ArchiveBox user [blue]{ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/blue] ({USER}).[/yellow]",
        )
    elif data_owned_by_root:
        STDERR.print(
            "\n[yellow]:warning: Warning: ArchiveBox [blue]DATA_DIR[/blue] appears to be owned by [red]root[/red]. If this is an NFS or mapped volume and writes work, no change is required.[/yellow]",
        )
    elif data_owner_doesnt_match:
        STDERR.print(
            f"\n[yellow]:warning: Warning: ArchiveBox [blue]DATA_DIR[/blue] is currently owned by [red]{data_dir_uid}:{data_dir_gid}[/red], but ArchiveBox user is [blue]{ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}[/blue] ({USER})! (ArchiveBox may not be able to write to the data dir)[/yellow]",
        )

    if data_not_writable:
        STDERR.print(
            f"[violet]Hint:[/violet] Change the current ownership [red]{data_dir_uid}[/red]:{data_dir_gid} to the user & group that will run ArchiveBox, e.g.:",
        )
        STDERR.print(f"    [grey53]sudo[/grey53] chown [blue]{DEFAULT_UID}:{DEFAULT_GID}[/blue] {DATA_DIR.resolve()}")
        STDERR.print("    Repair only specific nested paths if needed; do not recursively chown a large archive.")
        STDERR.print()
        STDERR.print("[blue]More info:[/blue]")
        STDERR.print(
            "    [link=https://github.com/ArchiveBox/ArchiveBox#storage-requirements]https://github.com/ArchiveBox/ArchiveBox#storage-requirements[/link]",
        )
        STDERR.print(
            "    [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#permissions]https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#permissions[/link]",
        )
        STDERR.print(
            "    [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#puid--pgid]https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#puid--pgid[/link]",
        )
        STDERR.print(
            "    [link=https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#filesystem-doesnt-support-fsync-eg-network-mounts]https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#filesystem-doesnt-support-fsync-eg-network-mounts[/link]",
        )

    from archivebox.config.common import get_config

    config = config or get_config(**config_kwargs)
    try:
        tmp_dir = get_or_create_working_tmp_dir(autofix=True, quiet=True, config=config) or config.TMP_DIR
    except Exception:
        tmp_dir = config.TMP_DIR

    try:
        lib_dir = get_or_create_working_lib_dir(autofix=True, quiet=True, config=config) or config.ABXPKG_LIB_DIR
    except Exception:
        lib_dir = config.ABXPKG_LIB_DIR

    # Check /tmp dir permissions
    check_tmp_dir(tmp_dir, throw=False, must_exist=True, config=config)

    # Check /lib dir permissions
    check_lib_dir(lib_dir, throw=False, must_exist=True, config=config)

    # Derive directory mode from file mode by OR-ing the execute bits (matches
    # the old DIR_OUTPUT_PERMISSIONS=755 vs OUTPUT_PERMISSIONS=644 convention).
    os.umask(0o777 - (int(config.OUTPUT_PERMISSIONS, base=8) | 0o111))


def check_tmp_dir(tmp_dir=None, throw=False, quiet=False, must_exist=True, config=None, **config_kwargs):
    from archivebox.config.paths import (
        MAX_TMP_SOCKET_URL_LENGTH,
        SUPERVISORD_SOCKET_FILENAME,
        assert_dir_can_contain_unix_sockets,
        dir_is_writable,
        get_or_create_working_tmp_dir,
        tmp_dir_socket_path_is_short_enough,
    )
    from archivebox.misc.logging import STDERR
    from archivebox.misc.logging_util import pretty_path
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP
    from archivebox.config.common import get_config

    config = config or get_config(**config_kwargs)
    tmp_dir = tmp_dir or config.TMP_DIR
    socket_file = tmp_dir.absolute().resolve() / SUPERVISORD_SOCKET_FILENAME

    if not must_exist and not os.path.isdir(tmp_dir):
        # just check that its viable based on its length (because dir may not exist yet, we cant check if its writable)
        return tmp_dir_socket_path_is_short_enough(tmp_dir)

    tmp_is_valid = False
    try:
        tmp_is_valid = dir_is_writable(tmp_dir)
        if not config.ALLOW_NO_UNIX_SOCKETS:
            tmp_is_valid = tmp_is_valid and assert_dir_can_contain_unix_sockets(tmp_dir)
        assert tmp_is_valid, f"ArchiveBox user {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} is unable to write to TMP_DIR={tmp_dir}"
        socket_url_len = len(f"file://{socket_file}")
        assert tmp_dir_socket_path_is_short_enough(tmp_dir), (
            f"ArchiveBox TMP_DIR={tmp_dir} is too long, file://{socket_file} is {socket_url_len} chars "
            f"and must be <{MAX_TMP_SOCKET_URL_LENGTH} chars."
        )
        return True
    except Exception as e:
        if not quiet:
            STDERR.print()
            ERROR_TEXT = "\n".join(
                (
                    "",
                    f"[red]:cross_mark: ArchiveBox is unable to use TMP_DIR={pretty_path(tmp_dir)}[/red]",
                    f"   [yellow]{e}[/yellow]",
                    "",
                    "[blue]Info:[/blue] [grey53]The TMP_DIR is used for the supervisord unix socket file and other temporary files.",
                    "  - It [red]must[/red] be on a local drive (not inside a docker volume, remote network drive, or FUSE mount).",
                    f"  - It [red]must[/red] be readable and writable by the ArchiveBox user ({ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}).",
                    "  - It [red]must[/red] be a *short* path (less than 90 characters) due to UNIX path length restrictions for sockets.",
                    "  - It [yellow]should[/yellow] be able to hold at least 200MB of data (in-progress downloads can be large).[/grey53]",
                    "",
                    "[violet]Hint:[/violet] Fix it by setting TMP_DIR to a path that meets these requirements, e.g.:",
                    f"      [green]archivebox config --set TMP_DIR={get_or_create_working_tmp_dir(autofix=False, quiet=True) or '/tmp/archivebox'}[/green]",
                    "",
                ),
            )
            STDERR.print(
                Panel(
                    ERROR_TEXT,
                    expand=False,
                    border_style="red",
                    title="[red]:cross_mark: Error with configured TMP_DIR[/red]",
                    subtitle="Background workers may fail to start until fixed.",
                ),
            )
            STDERR.print()
        if throw:
            raise OSError(f"TMP_DIR={tmp_dir} is invalid, ArchiveBox is unable to use it and the server will fail to start!") from e
    return False


def check_lib_dir(lib_dir: Path | None = None, throw=False, quiet=False, must_exist=True, config=None, **config_kwargs):
    from archivebox.config.permissions import ARCHIVEBOX_USER, ARCHIVEBOX_GROUP
    from archivebox.misc.logging import STDERR
    from archivebox.misc.logging_util import pretty_path
    from archivebox.config.paths import dir_is_writable, get_or_create_working_lib_dir
    from archivebox.config.common import get_config

    config = config or get_config(**config_kwargs)
    lib_dir = lib_dir or config.ABXPKG_LIB_DIR

    if not must_exist and not os.path.isdir(lib_dir):
        return True

    lib_is_valid = False
    try:
        lib_is_valid = dir_is_writable(lib_dir)
        assert lib_is_valid, f"ArchiveBox user {ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP} is unable to write to ABXPKG_LIB_DIR={lib_dir}"
        return True
    except Exception as e:
        if not quiet:
            STDERR.print()
            ERROR_TEXT = "\n".join(
                (
                    "",
                    f"[red]:cross_mark: ArchiveBox is unable to use ABXPKG_LIB_DIR={pretty_path(lib_dir)}[/red]",
                    f"   [yellow]{e}[/yellow]",
                    "",
                    "[blue]Info:[/blue] [grey53]The ABXPKG_LIB_DIR is used to store ArchiveBox auto-installed plugin library and binary dependencies.",
                    f"  - It [red]must[/red] be readable and writable by the ArchiveBox user ({ARCHIVEBOX_USER}:{ARCHIVEBOX_GROUP}).",
                    "  - It [yellow]should[/yellow] be on a local (ideally fast) drive like an SSD or HDD (not on a network drive or external HDD).",
                    "  - It [yellow]should[/yellow] be able to hold at least 1GB of data (some dependencies like Chrome can be large).[/grey53]",
                    "",
                    "[violet]Hint:[/violet] Fix it by setting ABXPKG_LIB_DIR to a path that meets these requirements, e.g.:",
                    f"      [green]archivebox config --set ABXPKG_LIB_DIR={get_or_create_working_lib_dir(autofix=False, quiet=True) or config.ABXPKG_LIB_DIR}[/green]",
                    "",
                ),
            )
            STDERR.print(
                Panel(
                    ERROR_TEXT,
                    expand=False,
                    border_style="red",
                    title="[red]:cross_mark: Error with configured ABXPKG_LIB_DIR[/red]",
                    subtitle="[yellow]Dependencies may not auto-install properly until fixed.[/yellow]",
                ),
            )
            STDERR.print()
        if throw:
            raise OSError(
                f"ABXPKG_LIB_DIR={lib_dir} is invalid, ArchiveBox is unable to use it and dependencies will fail to install.",
            ) from e
    return False
