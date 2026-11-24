"""Run Uvicorn with explicit listeners so [::] serves both IP families."""

import argparse
import asyncio
import logging
import socket
from contextlib import ExitStack
from ipaddress import IPv6Address, ip_address

import uvicorn
from uvicorn.supervisors import Multiprocess

from archivebox.workers.memory_observer import MemoryObserver


class WorkerApplication:
    """Initialize and close each spawned worker through ASGI lifespan."""

    def __init__(self):
        self.application = None

    @staticmethod
    def load():
        # Django startup reads the collection database. Do that outside the
        # event loop, independently in each worker rather than in the manager.
        from archivebox.core.asgi import application
        from archivebox.plugins.discovery import get_plugin_icon_sprite
        from django.urls import reverse
        from django.template.loader import get_template

        # The first browser should not pay for importing Django Ninja's API
        # routes and compiling the list template after the worker reports ready.
        # Resolve/compile only; search scope and results stay request-local.
        reverse("public-index")
        get_template("public_index.html")
        # Each plugin's parsed SVG is cached by discovery for the worker's
        # lifetime. Parse the catalog off the first table's render path.
        get_plugin_icon_sprite()

        return application

    @staticmethod
    def shutdown():
        from django.apps import apps

        for app in apps.get_app_configs():
            shutdown = getattr(app, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    logging.getLogger(__name__).exception("Application shutdown failed: %s", app.name)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "lifespan":
            assert self.application is not None, "Worker startup has not completed"
            return await self.application(scope, receive, send)

        message = await receive()
        assert message["type"] == "lifespan.startup"
        self.application = await asyncio.to_thread(self.load)
        observer = MemoryObserver().start()
        try:
            await send({"type": "lifespan.startup.complete"})
            message = await receive()
            assert message["type"] == "lifespan.shutdown"
        finally:
            stopped = await asyncio.to_thread(observer.stop)
            logging.getLogger("uvicorn.error").log(
                logging.INFO if stopped else logging.WARNING,
                "worker_memory_stopped" if stopped else "worker_memory_stop_pending",
            )
            await asyncio.to_thread(self.shutdown)
        await send({"type": "lifespan.shutdown.complete"})


application = WorkerApplication()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--ws-max-size", type=int, default=1048576)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    if args.workers is not None and args.workers < 1:
        parser.error("workers must be at least one")
    address = ip_address(args.host.strip("[]"))
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        if address.scope_id is not None:
            parser.error("IPv4-mapped addresses cannot have an IPv6 interface scope")
        address = address.ipv4_mapped
    host = str(address)
    config = uvicorn.Config(
        "archivebox.workers.http_server:application",
        host=host,
        port=args.port,
        lifespan="on",
        workers=args.workers,
        ws_max_size=args.ws_max_size,
        # Django owns proxy trust and must receive the original socket peer.
        proxy_headers=False,
        # A pipelined/keepalive request must not inherit the previous request's
        # context when the transport resumes reading during response delivery.
        reset_contextvars=True,
    )
    if config.workers < 1:
        parser.error("workers must be at least one")
    addresses = [(host, socket.AF_INET6 if ":" in host else socket.AF_INET)]
    if host == "::":
        # asyncio otherwise silently makes [::] IPv6-only. Separate sockets
        # also retain ordinary IPv4 peer addresses for Django's proxy checks.
        addresses.append(("0.0.0.0", socket.AF_INET))
    with ExitStack() as stack:
        sockets = []
        for address, family in addresses:
            # Preserve sin6_scope_id for link-local listeners. Passing only
            # (host%interface, port) to bind loses the scope on Linux.
            sockaddr = socket.getaddrinfo(address, args.port, family, socket.SOCK_STREAM, flags=socket.AI_NUMERICHOST)[0][4]
            sockets.append(stack.enter_context(socket.create_server(sockaddr, family=family)))
        # Match Uvicorn's bind_socket announcement for prebound listeners.
        for listener in sockets:
            logging.getLogger("uvicorn.error").info("Uvicorn running on socket %s", listener.getsockname())
        if config.workers > 1:
            Multiprocess(config, sockets=sockets).run()
        else:
            uvicorn.Server(config).run(sockets=sockets)


if __name__ == "__main__":
    main()
