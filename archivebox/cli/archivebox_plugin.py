"""Collection commands contributed by installed plugins."""

import rich_click as click

from archivebox.plugins.discovery import get_plugin_apps
from archivebox.plugins.host import host


@click.group()
def main():
    """Run a plugin's collection commands."""


for name, app in get_plugin_apps().items():
    getter = getattr(app, "get_cli_commands", None)
    if getter is None:
        continue
    group = click.Group(name=name)
    for command in getter(host):
        if command.name in group.commands:
            raise ValueError(f"Duplicate plugin command: {name} {command.name}")
        group.add_command(command)
    if group.commands:
        main.add_command(group)
