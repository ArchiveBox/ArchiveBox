"""Retain IPv6 interface scopes through Django's address parser."""

from ipaddress import IPv6Address

from daphne.management.commands.runserver import Command as DaphneCommand
from django.core.management import CommandError


class Command(DaphneCommand):
    def handle(self, *args, **options):
        self.ipv6_scope = None
        addrport = options.get("addrport") or ""
        if addrport.startswith("[") and "]:" in addrport:
            address, port = addrport[1:].split("]:", 1)
            if "%" in address:
                try:
                    self.ipv6_scope = IPv6Address(address).scope_id
                except ValueError as error:
                    raise CommandError(f"Invalid scoped IPv6 address: {address}") from error
                # Django validates the address/port without a scope. Restore
                # the scope in run() before the inherited server/reloader starts.
                options["addrport"] = f"[{address.split('%', 1)[0]}]:{port}"
        return super().handle(*args, **options)

    def run(self, **options):
        if self.ipv6_scope is not None:
            self.addr = f"{self.addr}%{self.ipv6_scope}"
        return super().run(**options)
