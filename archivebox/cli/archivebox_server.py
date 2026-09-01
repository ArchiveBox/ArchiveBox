#!/usr/bin/env python3

__package__ = "archivebox.cli"

import sys
import os
import socket
import subprocess
import time
from collections.abc import Iterable

import rich_click as click
from rich import print
from rich.style import Style
from rich.text import Text

from archivebox.config import CONSTANTS
from archivebox.misc.util import docstring, enforce_types


import re as _re

_IPV4_RE = _re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_IPV6_CHARS_RE = _re.compile(r"^[0-9a-fA-F:.]+$")
_LOCAL_BIND_HOSTS = frozenset({"0.0.0.0", "::", "::0", "127.0.0.1", "::1"})


def _is_ipv4_literal(host: str) -> bool:
    return bool(_IPV4_RE.match(host))


def _is_ipv6_literal(host: str) -> bool:
    # Bracketed (e.g. ``[2001:db8::1]``) or bare form. Require at least two
    # colons so we don't catch random strings with one ``:``.
    stripped = host.strip("[]")
    return stripped.count(":") >= 2 and bool(_IPV6_CHARS_RE.match(stripped))


def _bind_host_looks_like_ip(host: str) -> bool:
    if not host or host in _LOCAL_BIND_HOSTS:
        return False
    return _is_ipv4_literal(host) or _is_ipv6_literal(host)


def _split_bind_spec(spec: str) -> tuple[str, str]:
    """Split a ``host:port`` / ``host`` / ``port`` spec into ``(host, port)``.

    The empty strings stand in for "not provided"; the caller fills in
    defaults. Bracketed IPv6 literals like ``[::1]:8000`` are handled.
    """
    spec = (spec or "").strip()
    if not spec:
        return "", ""
    if spec.startswith("["):
        # Bracketed IPv6: ``[::1]`` or ``[::1]:8000``
        end = spec.find("]")
        if end == -1:
            return spec, ""  # malformed; let validator reject it
        host = spec[: end + 1]
        rest = spec[end + 1 :]
        if rest.startswith(":"):
            return host, rest[1:]
        return host, ""
    if ":" in spec:
        host, _, port = spec.rpartition(":")
        return host, port
    # Bare token: digits = port, anything else = host
    if spec.isdigit():
        return "", spec
    return spec, ""


def _parse_and_validate_bind_spec(spec: str) -> tuple[str, str]:
    """Resolve a CLI/config bind spec to ``(host, port)`` or hard-error.

    Accepts only IP literals (v4 or v6) or the special string ``localhost``
    (normalized to ``127.0.0.1``). Bare hostnames are rejected because the
    bind address feeds Daphne, which has to listen on a numeric address;
    public hostnames belong in ``BASE_URL`` instead. Empty values fall back
    to ``127.0.0.1`` / ``8000``.
    """
    raw_host, raw_port = _split_bind_spec(spec)
    host = raw_host.strip()
    port = (raw_port or "").strip() or "8000"

    if host == "" or host.lower() == "localhost":
        host = "127.0.0.1"
    elif _is_ipv4_literal(host) or _is_ipv6_literal(host):
        pass
    else:
        print(
            f"[red][X] Invalid BIND_ADDR host {host!r}: must be an IP literal or 'localhost'.[/red]",
        )
        print(
            "[red]    Hostnames like archive.example.com are not valid bind addresses — Daphne[/red]",
        )
        print(
            "[red]    listens on numeric addresses only. Bind to 0.0.0.0 and set BASE_URL instead:[/red]",
        )
        print(
            f"[red]      BASE_URL=https://{host} archivebox server 0.0.0.0:{port}[/red]",
        )
        sys.exit(1)

    try:
        port_int = int(port)
    except ValueError:
        print(f"[red][X] Invalid BIND_ADDR port {port!r}: must be an integer 1-65535.[/red]")
        sys.exit(1)
    if not (0 < port_int < 65536):
        print(f"[red][X] Invalid BIND_ADDR port {port_int}: must be 1-65535.[/red]")
        sys.exit(1)

    return host, port


def _print_server_startup_warnings(config, host: str, port: str) -> None:
    """Print startup-time security / routing warnings for the server command.

    Runs only from ``archivebox server`` so other entry points (manage shell,
    plugin lookups, etc.) don't repeat this banner on every config load.
    """
    if config.IS_LOWER_SECURITY_MODE:
        print(
            f"[yellow][!] WARNING: ArchiveBox is running with SERVER_SECURITY_MODE={config.SERVER_SECURITY_MODE}[/yellow]",
        )
        print("[yellow]    Archived pages may share an origin with privileged app routes in this mode.[/yellow]")
        print("[yellow]    To switch to the safer isolated setup:[/yellow]")
        print("[yellow]      1. Set SERVER_SECURITY_MODE=safe-subdomains-fullreplay[/yellow]")
        print("[yellow]      2. Point *.archivebox.localhost (or your chosen base domain) at this server[/yellow]")
        print(
            "[yellow]      3. Configure wildcard DNS/TLS or your reverse proxy so admin., web., api., and snapshot subdomains resolve[/yellow]",
        )
        print()

    # ``config.BASE_URL`` is the merged value (env > Machine.config > file >
    # default), which is what the running server will actually use. Earlier we
    # gated the "BASE_URL not set" warning on ``os.environ["BASE_URL"]`` alone,
    # which fired noisily when the user pinned BASE_URL via Machine.config /
    # ArchiveBox.conf instead of via env.
    base_url = (config.BASE_URL or "").strip()
    if base_url:
        # BASE_URL is pinned. The only thing left to surface is a port
        # mismatch — bind port ≠ BASE_URL's explicit port usually means the
        # operator started the server with the wrong ``archivebox server PORT``
        # argument (or forgot to update one side after moving the listener).
        # A reverse-proxy setup typically omits the port in BASE_URL
        # (``https://archive.example.com``), so we only warn when BASE_URL
        # carries an explicit port — otherwise we'd nag every proxy deployment.
        from urllib.parse import urlparse

        try:
            base_port = urlparse(base_url).port
        except (ValueError, TypeError):
            base_port = None
        if base_port is not None and str(base_port) != str(port):
            print(
                f"[yellow][!] BASE_URL ({base_url}) port {base_port} does not match the port the server is running on ({port}). "
                "Make sure this is intentional![/yellow]",
            )
            print()
        return

    # If the user is upgrading from 0.7.3 and already had
    # CSRF_TRUSTED_ORIGINS set, get_base_url() will silently use that as the
    # implicit BASE_URL. Surface what we picked so the user knows where their
    # links / redirects are going — and tell them how to make it explicit.
    from archivebox.core.routes_util import derive_base_url_from_csrf

    csrf_derived = derive_base_url_from_csrf(config)
    if csrf_derived:
        print(
            f"[yellow][!] BASE_URL is not set; auto-derived [bold]{csrf_derived}[/bold] from a single CSRF_TRUSTED_ORIGINS entry.[/yellow]",
        )
        print(
            "[yellow]    Links / redirects / cookies will use that origin. To silence this hint, set BASE_URL[/yellow]",
        )
        print(
            f"[yellow]    explicitly: [bold]BASE_URL={csrf_derived}[/bold] (matches your existing CSRF_TRUSTED_ORIGINS).[/yellow]",
        )
        print()
        return

    # BASE_URL was not set explicitly. The routes_util derivation gives one of
    # three results, with very different risk profiles — show a tailored hint
    # so new users coming from the 0.7.x single-domain world know whether the
    # default is fine for them or needs attention.
    if _bind_host_looks_like_ip(host):
        # Real IP literal: subdomain routing can't work, URLs leak the IP.
        # This is the most urgent case.
        print(
            f"[yellow][!] WARNING: BASE_URL is not set and BIND_ADDR resolves to an IP literal ({host}).[/yellow]",
        )
        print(
            "[yellow]    Snapshot / admin / api URLs will be generated with the IP, and subdomain[/yellow]",
        )
        print(
            "[yellow]    routing cannot work against an IP address. Set BASE_URL explicitly, e.g.[/yellow]",
        )
        print(
            "[yellow]      BASE_URL=https://archive.example.com archivebox server 0.0.0.0:8000[/yellow]",
        )
        if config.USES_SUBDOMAIN_ROUTING:
            print(
                "[yellow]    Or switch SERVER_SECURITY_MODE to a one-domain mode if you can't run a hostname.[/yellow]",
            )
        print()
    else:
        # Loopback / wildcard bind. The routes_util default of
        # http://archivebox.localhost:PORT works in a browser on the same
        # machine, but anything else (reverse proxy, k8s ingress, LAN client)
        # needs BASE_URL set. (Real hostnames can't reach this branch — the
        # bind validator rejects them upfront.)
        print(
            "[yellow][!] BASE_URL is not set. Generated URLs will fall back to http://archivebox.localhost:<port>.[/yellow]",
        )
        print(
            "[yellow]    That's fine for local browsing on this machine. Set BASE_URL when running behind[/yellow]",
        )
        print(
            "[yellow]    a reverse proxy / ingress / public hostname, e.g.[/yellow]",
        )
        print(
            "[yellow]      BASE_URL=https://archive.example.com archivebox server 0.0.0.0:8000[/yellow]",
        )
        print()


@enforce_types
def server(
    runserver_args: Iterable[str] | None = None,
    reload: bool = False,
    debug: bool = False,
    daemonize: bool = False,
    nothreading: bool = False,
    createsuperuser: bool = False,
) -> None:
    """Run the ArchiveBox HTTP server"""
    from archivebox.config.common import get_config

    config = get_config()
    runserver_args = list(runserver_args or (config.BIND_ADDR,))

    run_in_debug = config.DEBUG or debug or reload
    if debug or reload:
        os.environ["DEBUG"] = "True"

    from django.contrib.auth.models import User

    if createsuperuser:
        from archivebox.cli.archivebox_manage import manage

        manage(args=["createsuperuser"])
        print()

    # First non-empty positional arg is the bind spec; otherwise inherit from
    # config (which defaults to "127.0.0.1:8000"). _parse_and_validate_bind_spec
    # hard-errors on hostnames so the rest of the server can assume a numeric
    # bind host.
    bind_spec = next((arg for arg in runserver_args if arg), "")
    host, port = _parse_and_validate_bind_spec(bind_spec)

    if not User.objects.filter(is_superuser=True).exclude(username="system").exists():
        from archivebox.core.routes_util import build_admin_url

        print()
        print("[violet]Hint:[/violet] Open the Admin UI to create the first admin and finish web setup:")
        runtime_config = config.model_copy(update={"BIND_ADDR": f"{host}:{port}"})
        print(f"      [green]{build_admin_url('/admin/', config=runtime_config)}[/green]")
        if not config.BASE_URL and host not in ("127.0.0.1", "localhost"):
            print("      (When running remotely, replace localhost with this server's IP address or hostname.)")
        print()

    if daemonize and os.environ.get("ARCHIVEBOX_SERVER_DAEMON_CHILD") != "1":
        from archivebox.workers.supervisord_util import resolve_env_binary

        log_path = CONSTANTS.LOGS_DIR / "server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        daemon_env = os.environ.copy()
        daemon_env["ARCHIVEBOX_SERVER_DAEMON_CHILD"] = "1"
        daemon_cmd = [str(resolve_env_binary("archivebox")), "server"]
        if debug:
            daemon_cmd.append("--debug")
        if reload:
            daemon_cmd.append("--reload")
        if nothreading:
            daemon_cmd.append("--nothreading")
        daemon_cmd.extend(runserver_args)
        with log_path.open("a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                daemon_cmd,
                cwd=os.getcwd(),
                env=daemon_env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                print(f"[red][X] ArchiveBox daemon server exited early with code {proc.returncode}. See {log_path}[/red]")
                sys.exit(proc.returncode or 1)
            try:
                with socket.create_connection((host, int(port)), timeout=0.25):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            print(f"[red][X] ArchiveBox daemon server pid={proc.pid} did not become ready. See {log_path}[/red]")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            sys.exit(1)
        return

    os.environ["BIND_ADDR"] = f"{host}:{port}"
    from archivebox.core.routes_util import get_base_url

    base_url = get_base_url().rstrip("/")
    admin_url = f"{base_url}/admin/"

    from archivebox.workers.supervisord_util import (
        active_supervisord_runtime_components,
        format_runtime_components,
        start_server_workers,
        stop_existing_supervisord_process,
        is_port_in_use,
    )
    from archivebox.machine.models import Process
    from archivebox.core.takeover_util import (
        command_owns_runtime_stack,
        current_command,
        foreground_runner_owner,
        runtime_stack_owner,
        standby_until_runtime_stack_needed,
    )
    from archivebox.core.shutdown_util import foreground_parent_watchdog, foreground_shutdown_signals

    if run_in_debug:
        print("[green][+] Starting ArchiveBox webserver in DEBUG mode...[/green]")
    else:
        print("[green][+] Starting ArchiveBox webserver...[/green]")
    bind_url = f"http://{host}:{port}"
    bind_message = Text.from_markup(
        "    [blink][green]>[/green][/blink] Starting ArchiveBox webserver on [dim]BIND_ADDR[/dim] ",
    )
    bind_message.append(bind_url, style=Style(color="deep_sky_blue4", link=bind_url))
    print(bind_message)
    admin_message = Text.from_markup("    [green]>[/green] Log in to ArchiveBox Admin UI on [dim]BASE_URL [/dim] ")
    admin_message.append(admin_url, style=Style(color="deep_sky_blue3", link=admin_url))
    print(admin_message)
    print("    > Writing ArchiveBox error log to ./logs/errors.log")
    print()

    # Reload config after we've set os.environ["BIND_ADDR"] above so the
    # security-mode + base-url warnings see the effective values.
    runtime_config = get_config()
    _print_server_startup_warnings(runtime_config, host, port)
    command = current_command(Process.TypeChoices.SERVER, data_dir=CONSTANTS.DATA_DIR, url=bind_url)

    def still_owns_runtime_stack() -> bool:
        from django.db import connections

        try:
            return command_owns_runtime_stack(command, data_dir=CONSTANTS.DATA_DIR)
        finally:
            connections.close_all()

    shutdown_state = None
    try:
        with (
            foreground_shutdown_signals() as shutdown_state,
            foreground_parent_watchdog(enabled=os.environ.get("ARCHIVEBOX_SERVER_DAEMON_CHILD") != "1"),
        ):
            while True:
                standby_result = standby_until_runtime_stack_needed(command, data_dir=CONSTANTS.DATA_DIR)
                older_owner = runtime_stack_owner(data_dir=CONSTANTS.DATA_DIR, exclude_id=command.id) or foreground_runner_owner(
                    data_dir=CONSTANTS.DATA_DIR,
                    exclude_id=command.id,
                )
                takeover_components = active_supervisord_runtime_components()
                if older_owner and takeover_components:
                    print(
                        "[yellow][*] Taking over "
                        f"{format_runtime_components(takeover_components)} from older existing archivebox process (pid={older_owner.pid}).[/yellow]",
                    )
                stop_existing_supervisord_process()
                if is_port_in_use(host, int(port)):
                    print(f"[red][X] Error: Port {port} is already in use[/red]")
                    print(f"    Another process outside this ArchiveBox runtime is listening on {host}:{port}")
                    sys.exit(1)

                result = start_server_workers(
                    host=host,
                    port=port,
                    daemonize=False,
                    debug=run_in_debug,
                    reload=reload,
                    nothreading=nothreading,
                    keep_running=still_owns_runtime_stack,
                    should_stop_supervisord=still_owns_runtime_stack,
                    resumed_from_pid=standby_result.get("previous_owner_pid") if standby_result.get("resumed") else None,
                )
                if result == "interrupted":
                    break
                if not still_owns_runtime_stack():
                    continue
                if result == "exited":
                    print("[yellow][*] Runtime stack exited while this parent is still leader; restarting...[/yellow]")
                    continue
                break
    except KeyboardInterrupt:
        pass
    finally:
        if not shutdown_state or not shutdown_state.signal_name:
            command.mark_exited()
    print("\n[i][green][🟩] ArchiveBox server shut down gracefully.[/green][/i]")


@click.command()
@click.argument("runserver_args", nargs=-1)
@click.option("--reload", is_flag=True, help="Enable auto-reloading when code or templates change")
@click.option("--debug", is_flag=True, help="Enable DEBUG=True mode with more verbose errors")
@click.option("--nothreading", is_flag=True, help="Force runserver to run in single-threaded mode")
@click.option("--daemonize", is_flag=True, help="Run the server in the background as a daemon")
@click.option("--createsuperuser", is_flag=True, help="Run archivebox manage createsuperuser before starting the server")
@docstring(server.__doc__)
def main(**kwargs):
    server(**kwargs)


if __name__ == "__main__":
    main()
