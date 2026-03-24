#!/usr/bin/env python3

__package__ = "archivebox.cli"


import rich_click as click

from archivebox.misc.util import docstring, enforce_types


EVENT_FLOW_DIAGRAM = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ArchiveBox / abx-dl Flow                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  InstallEvent                                                               │
│    └─ config.json > required_binaries                                       │
│         └─ BinaryRequestEvent                                               │
│              └─ on_BinaryRequest__*                                         │
│                   └─ BinaryEvent                                            │
│                                                                             │
│  CrawlEvent                                                                 │
│    └─ CrawlSetupEvent                                                       │
│         └─ on_CrawlSetup__*                                                 │
│                                                                             │
│  CrawlStartEvent                                                            │
│    └─ SnapshotEvent                                                         │
│         └─ on_Snapshot__*                                                   │
│              └─ Snapshot / ArchiveResult / Tag / Machine / BinaryRequest    │
│                                                                             │
│  SnapshotCleanupEvent  -> internal cleanup, no direct hook family           │
│  CrawlCleanupEvent     -> internal cleanup, no direct hook family           │
│                                                                             │
│  ArchiveBox projects bus events into the DB; it no longer drives plugin     │
│  execution through the old queued model executor.                           │
└─────────────────────────────────────────────────────────────────────────────┘
"""


@enforce_types
def pluginmap(
    show_disabled: bool = False,
    event: str | None = None,
    quiet: bool = False,
) -> dict:
    """
    Show the current abx-dl event phases and their associated plugin hooks.

    This command reflects the new bus-driven runtime, not the legacy ArchiveBox
    state-machine executor. Event names are normalized to hook prefixes by
    stripping a trailing `Event`, then ArchiveBox checks whether any matching
    `on_{EventFamily}__*` scripts actually exist.
    """
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box

    from archivebox.hooks import (
        BUILTIN_PLUGINS_DIR,
        USER_PLUGINS_DIR,
        discover_hooks,
        is_background_hook,
        normalize_hook_event_name,
    )

    console = Console()
    prnt = console.print

    event_phases = {
        "InstallEvent": {
            "description": "Pre-run dependency phase. Enabled plugins emit BinaryRequest events from config.json required_binaries.",
            "emits": ["BinaryRequestEvent", "BinaryEvent", "ProcessEvent"],
        },
        "BinaryRequestEvent": {
            "description": "Provider phase. on_BinaryRequest hooks resolve or install requested binaries.",
            "emits": ["BinaryEvent", "ProcessEvent"],
        },
        "BinaryEvent": {
            "description": "Resolved binary metadata event. Projected into the DB binary cache.",
            "emits": [],
        },
        "CrawlEvent": {
            "description": "Root crawl lifecycle event emitted by the runner.",
            "emits": ["CrawlSetupEvent", "CrawlStartEvent", "CrawlCleanupEvent", "CrawlCompletedEvent"],
        },
        "CrawlSetupEvent": {
            "description": "Crawl-scoped setup phase. on_CrawlSetup hooks launch/configure shared daemons and runtime state.",
            "emits": ["ProcessEvent"],
        },
        "SnapshotEvent": {
            "description": "Per-snapshot extraction phase. on_Snapshot hooks emit ArchiveResult, Snapshot, Tag, and BinaryRequest records.",
            "emits": ["ArchiveResultEvent", "SnapshotEvent", "TagEvent", "BinaryRequestEvent", "ProcessEvent"],
        },
        "SnapshotCleanupEvent": {
            "description": "Internal snapshot cleanup phase.",
            "emits": ["ProcessKillEvent"],
        },
        "CrawlCleanupEvent": {
            "description": "Internal crawl cleanup phase.",
            "emits": ["ProcessKillEvent"],
        },
    }

    if event:
        requested = str(event).strip()
        if requested in event_phases:
            event_phases = {requested: event_phases[requested]}
        else:
            normalized_requested = normalize_hook_event_name(requested)
            matched_name = next((name for name in event_phases if normalize_hook_event_name(name) == normalized_requested), None)
            if matched_name is None:
                prnt(f'[red]Error: Unknown event "{requested}". Available: {", ".join(event_phases.keys())}[/red]')
                return {}
            event_phases = {matched_name: event_phases[matched_name]}

    result = {
        "events": {},
        "plugins_dir": str(BUILTIN_PLUGINS_DIR),
        "user_plugins_dir": str(USER_PLUGINS_DIR),
    }

    if not quiet:
        prnt()
        prnt("[bold cyan]ArchiveBox Plugin Map[/bold cyan]")
        prnt(f"[dim]Built-in plugins: {BUILTIN_PLUGINS_DIR}[/dim]")
        prnt(f"[dim]User plugins: {USER_PLUGINS_DIR}[/dim]")
        prnt()
        prnt(
            Panel(
                EVENT_FLOW_DIAGRAM,
                title="[bold green]Event Flow[/bold green]",
                border_style="green",
                expand=False,
            ),
        )
        prnt()

    for event_name, info in event_phases.items():
        hook_event = normalize_hook_event_name(event_name)
        hooks = discover_hooks(event_name, filter_disabled=not show_disabled)

        hook_infos = []
        for hook_path in hooks:
            plugin_name = hook_path.parent.name
            hook_infos.append(
                {
                    "path": str(hook_path),
                    "name": hook_path.name,
                    "plugin": plugin_name,
                    "is_background": is_background_hook(hook_path.name),
                    "extension": hook_path.suffix,
                },
            )

        result["events"][event_name] = {
            "description": info["description"],
            "hook_event": hook_event,
            "emits": info["emits"],
            "hooks": hook_infos,
            "hook_count": len(hook_infos),
        }

        if quiet:
            continue

        title_suffix = f" -> on_{hook_event}__*" if hook_infos else ""
        table = Table(
            title=f"[bold yellow]{event_name}[/bold yellow]{title_suffix} ({len(hooks)} hooks)",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Plugin", style="cyan", width=20)
        table.add_column("Hook Name", style="green")
        table.add_column("BG", justify="center", width=4)
        table.add_column("Type", justify="center", width=5)

        if hook_infos:
            for hook in sorted(hook_infos, key=lambda h: h["name"]):
                bg_marker = "[yellow]bg[/yellow]" if hook["is_background"] else ""
                table.add_row(
                    hook["plugin"],
                    hook["name"],
                    bg_marker,
                    hook["extension"].lstrip("."),
                )
        else:
            table.add_row("[dim]-[/dim]", "[dim]No direct hooks[/dim]", "", "")

        prnt(table)
        prnt(f"[dim]{info['description']}[/dim]")
        if info["emits"]:
            prnt(f"[dim]Emits: {', '.join(info['emits'])}[/dim]")
        if not hook_infos:
            prnt(f"[dim]No direct on_{hook_event}__* scripts are currently defined for this event family.[/dim]")
        prnt()

    if not quiet:
        total_hooks = sum(event_info["hook_count"] for event_info in result["events"].values())
        prnt(f"[bold]Total hooks discovered: {total_hooks}[/bold]")
        prnt()
        prnt("[dim]Hook naming convention: on_{EventFamily}__{XX}_{description}[.bg].{ext}[/dim]")
        prnt("[dim]Event names are normalized with a simple `Event` suffix strip before hook discovery.[/dim]")
        prnt("[dim]If no `on_{EventFamily}__*` scripts exist, the event is shown as having no direct hooks.[/dim]")
        prnt()

    return result


@click.command()
@click.option("--show-disabled", "-a", is_flag=True, help="Show hooks from disabled plugins too")
@click.option("--event", "-e", type=str, default=None, help="Filter to specific event (e.g. InstallEvent, SnapshotEvent)")
@click.option("--quiet", "-q", is_flag=True, help="Output JSON only, no tables")
@docstring(pluginmap.__doc__)
def main(**kwargs):
    import json

    result = pluginmap(**kwargs)
    if kwargs.get("quiet"):
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
