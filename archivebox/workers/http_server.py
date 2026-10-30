"""Run Uvicorn with explicit listeners so [::] serves both IP families."""

import argparse
import logging
import socket
from contextlib import ExitStack
from ipaddress import IPv6Address, ip_address

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--ws-max-size", type=int, default=1048576)
    parser.add_argument("--lifespan", choices=("off",), default="off")
    args = parser.parse_args()
    address = ip_address(args.host.strip("[]"))
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        if address.scope_id is not None:
            parser.error("IPv4-mapped addresses cannot have an IPv6 interface scope")
        address = address.ipv4_mapped
    host = str(address)
    config = uvicorn.Config(
        "archivebox.core.asgi:application",
        host=host,
        port=args.port,
        lifespan=args.lifespan,
        ws_max_size=args.ws_max_size,
        # Django owns proxy trust and must receive the original socket peer.
        proxy_headers=False,
    )
    # Django initialization performs synchronous database reads. Load before
    # Server.run enters the event loop, as Uvicorn's CLI does.
    config.load()
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
        uvicorn.Server(config).run(sockets=sockets)


if __name__ == "__main__":
    main()
