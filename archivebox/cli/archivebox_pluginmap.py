#!/usr/bin/env python3

__package__ = 'archivebox.cli'

from typing import Optional
from pathlib import Path

import rich_click as click

from archivebox.misc.util import docstring, enforce_types


# State Machine ASCII Art Diagrams
CRAWL_MACHINE_DIAGRAM = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CrawlMachine                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐                                                           │
│   │   QUEUED    │◄────────────────┐                                         │
│   │  (initial)  │                 │                                         │
│   └──────┬──────┘                 │                                         │
│          │                        │ tick() unless can_start()               │
│          │ tick() when            │                                         │
│          │ can_start()            │                                         │
│          ▼                        │                                         │
│   ┌─────────────┐                 │                                         │
│   │   STARTED   │─────────────────┘                                         │
│   │             │◄────────────────┐                                         │
│   │ enter:      │                 │                                         │
│   │  crawl.run()│                 │ tick() unless is_finished()             │
│   │  (discover  │                 │                                         │
│   │   Crawl     │─────────────────┘                                         │
│   │   hooks)    │                                                           │
│   └──────┬──────┘                                                           │
│          │                                                                  │
│          │ tick() when is_finished()                                        │
│          ▼                                                                  │
│   ┌─────────────┐                                                           │
│   │   SEALED    │                                                           │
│   │   (final)   │                                                           │
│   │             │                                                           │
│   │ enter:      │                                                           │
│   │  cleanup()  │                                                           │
│   └─────────────┘                                                           │
│                                                                             │
│   Hooks triggered: on_Crawl__* (during STARTED.enter via crawl.run())       │
│                    on_CrawlEnd__* (during SEALED.enter via cleanup())       │
└─────────────────────────────────────────────────────────────────────────────┘
"""

SNAPSHOT_MACHINE_DIAGRAM = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SnapshotMachine                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐                                                           │
│   │   QUEUED    │◄────────────────┐                                         │
│   │  (initial)  │                 │                                         │
│   └──────┬──────┘                 │                                         │
│          │                        │ tick() unless can_start()               │
│          │ tick() when            │                                         │
│          │ can_start()            │                                         │
│          ▼                        │                                         │
│   ┌─────────────┐                 │                                         │
│   │   STARTED   │─────────────────┘                                         │
│   │             │◄────────────────┐                                         │
│   │ enter:      │                 │                                         │
│   │ snapshot    │                 │ tick() unless is_finished()             │
│   │  .run()     │                 │                                         │
│   │ (discover   │─────────────────┘                                         │
│   │  Snapshot   │                                                           │
│   │  hooks,     │                                                           │
│   │  create     │                                                           │
│   │  pending    │                                                           │
│   │  results)   │                                                           │
│   └──────┬──────┘                                                           │
│          │                                                                  │
│          │ tick() when is_finished()                                        │
│          ▼                                                                  │
│   ┌─────────────┐                                                           │
│   │   SEALED    │                                                           │
│   │   (final)   │                                                           │
│   │             │                                                           │
│   │ enter:      │                                                           │
│   │  cleanup()  │                                                           │
│   └─────────────┘                                                           │
│                                                                             │
│   Hooks triggered: on_Snapshot__* (creates ArchiveResults in STARTED.enter) │
└─────────────────────────────────────────────────────────────────────────────┘
"""

ARCHIVERESULT_MACHINE_DIAGRAM = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ArchiveResultMachine                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐                                                           │
│   │   QUEUED    │◄─────────────────┐                                        │
│   │  (initial)  │                  │                                        │
│   └──┬───────┬──┘                  │                                        │
│      │       │                     │ tick() unless can_start()              │
│      │       │ exceeded_max_       │                                        │
│      │       │ attempts            │                                        │
│      │       ▼                     │                                        │
│      │  ┌──────────┐               │                                        │
│      │  │ SKIPPED  │               │                                        │
│      │  │ (final)  │               │                                        │
│      │  └──────────┘               │                                        │
│      │ tick() when                 │                                        │
│      │ can_start()                 │                                        │
│      ▼                             │                                        │
│   ┌─────────────┐                  │                                        │
│   │   STARTED   │──────────────────┘                                        │
│   │             │◄─────────────────────────────────────────────────┐        │
│   │ enter:      │                      │                           │        │
│   │ result.run()│ tick() unless        │                           │        │
│   │ (execute    │ is_finished()        │                           │        │
│   │  hook via   │──────────────────────┘                           │        │
│   │  run_hook())│                                                  │        │
│   └──────┬──────┘                                                  │        │
│          │                                                         │        │
│          │ tick() checks status set by hook output                 │        │
│          ├─────────────┬─────────────┬─────────────┐               │        │
│          ▼             ▼             ▼             ▼               │        │
│   ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐         │        │
│   │ SUCCEEDED │ │  FAILED   │ │  SKIPPED  │ │  BACKOFF  │         │        │
│   │  (final)  │ │  (final)  │ │  (final)  │ │           │         │        │
│   └───────────┘ └───────────┘ └───────────┘ └──┬──────┬─┘         │        │
│                                                 │      │            │        │
│                                   exceeded_max_ │      │ can_start()│        │
│                                   attempts      │      │ loops back │        │
│                                        ▼        │      └────────────┘        │
│                                   ┌──────────┐  │                            │
│                                   │ SKIPPED  │◄─┘                            │
│                                   │ (final)  │                               │
│                                   └──────────┘                               │
│                                                                             │
│   Each ArchiveResult runs ONE specific hook (stored in .hook_name field)    │
└─────────────────────────────────────────────────────────────────────────────┘
"""

BINARY_MACHINE_DIAGRAM = """
┌─────────────────────────────────────────────────────────────────────────────┐
│                             BinaryMachine                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐                                                           │
│   │   QUEUED    │◄────────────────┐                                         │
│   │  (initial)  │                 │                                         │
│   └──────┬──────┘                 │                                         │
│          │                        │ tick() unless can_install()             │
│          │                        │ (stays queued if failed)                │
│          │ tick() when            │                                         │
│          │ can_install()          │                                         │
│          │                        │                                         │
│          │ on_install() runs      │                                         │
│          │ during transition:     │                                         │
│          │  • binary.run()        │                                         │
│          │    (discover Binary    │                                         │
│          │     hooks, try each    │                                         │
│          │     provider until     │                                         │
│          │     one succeeds)      │                                         │
│          │  • Sets abspath,       │                                         │
│          │    version, sha256     │                                         │
│          │                        │                                         │
│          │ If install fails:      │                                         │
│          │  raises exception──────┘                                         │
│          │  (retry_at bumped)                                               │
│          │                                                                  │
│          ▼                                                                  │
│   ┌─────────────┐                                                           │
│   │  INSTALLED  │                                                           │
│   │   (final)   │                                                           │
│   │             │                                                           │
│   │ Binary is   │                                                           │
│   │ ready to    │                                                           │
│   │ use         │                                                           │
│   └─────────────┘                                                           │
│                                                                             │
│   Hooks triggered: on_Binary__* (provider hooks during transition)          │
│   Providers tried in sequence until one succeeds: apt, brew, pip, npm, etc. │
│   Installation is synchronous - no intermediate STARTED state               │
└─────────────────────────────────────────────────────────────────────────────┘
"""


@enforce_types
def pluginmap(
    show_disabled: bool = False,
    model: Optional[str] = None,
    quiet: bool = False,
) -> dict:
    """
    Show a map of all state machines and their associated plugin hooks.

    Displays ASCII art diagrams of the core model state machines (Crawl, Snapshot,
    ArchiveResult, Binary) and lists all auto-detected on_Modelname_xyz hooks
    that will run for each model's transitions.
    """
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box

    from archivebox.hooks import (
        discover_hooks,
        is_background_hook,
        BUILTIN_PLUGINS_DIR,
        USER_PLUGINS_DIR,
    )

    console = Console()
    prnt = console.print

    # Model event types that can have hooks
    model_events = {
        'Crawl': {
            'description': 'Hooks run when a Crawl starts (QUEUED→STARTED)',
            'machine': 'CrawlMachine',
            'diagram': CRAWL_MACHINE_DIAGRAM,
        },
        'CrawlEnd': {
            'description': 'Hooks run when a Crawl finishes (STARTED→SEALED)',
            'machine': 'CrawlMachine',
            'diagram': None,  # Part of CrawlMachine
        },
        'Snapshot': {
            'description': 'Hooks run for each Snapshot (creates ArchiveResults)',
            'machine': 'SnapshotMachine',
            'diagram': SNAPSHOT_MACHINE_DIAGRAM,
        },
        'Binary': {
            'description': 'Hooks for installing binary dependencies (providers)',
            'machine': 'BinaryMachine',
            'diagram': BINARY_MACHINE_DIAGRAM,
        },
    }

    # Filter to specific model if requested
    if model:
        model = model.title()
        if model not in model_events:
            prnt(f'[red]Error: Unknown model "{model}". Available: {", ".join(model_events.keys())}[/red]')
            return {}
        model_events = {model: model_events[model]}

    result = {
        'models': {},
        'plugins_dir': str(BUILTIN_PLUGINS_DIR),
        'user_plugins_dir': str(USER_PLUGINS_DIR),
    }

    if not quiet:
        prnt()
        prnt('[bold cyan]ArchiveBox Plugin Map[/bold cyan]')
        prnt(f'[dim]Built-in plugins: {BUILTIN_PLUGINS_DIR}[/dim]')
        prnt(f'[dim]User plugins: {USER_PLUGINS_DIR}[/dim]')
        prnt()

    # Show diagrams first (unless quiet mode)
    if not quiet:
        # Show ArchiveResult diagram separately since it's different
        prnt(Panel(
            ARCHIVERESULT_MACHINE_DIAGRAM,
            title='[bold green]ArchiveResultMachine[/bold green]',
            border_style='green',
            expand=False,
        ))
        prnt()

    for event_name, info in model_events.items():
        # Discover hooks for this event
        hooks = discover_hooks(event_name, filter_disabled=not show_disabled)

        # Build hook info list
        hook_infos = []
        for hook_path in hooks:
            # Get plugin name from parent directory (e.g., 'wget' from 'plugins/wget/on_Snapshot__06_wget.bg.py')
            plugin_name = hook_path.parent.name
            is_bg = is_background_hook(hook_path.name)

            hook_infos.append({
                'path': str(hook_path),
                'name': hook_path.name,
                'plugin': plugin_name,
                'is_background': is_bg,
                'extension': hook_path.suffix,
            })

        result['models'][event_name] = {
            'description': info['description'],
            'machine': info['machine'],
            'hooks': hook_infos,
            'hook_count': len(hook_infos),
        }

        if not quiet:
            # Show diagram if this model has one
            if info.get('diagram'):
                prnt(Panel(
                    info['diagram'],
                    title=f'[bold green]{info["machine"]}[/bold green]',
                    border_style='green',
                    expand=False,
                ))
                prnt()

            # Create hooks table
            table = Table(
                title=f'[bold yellow]on_{event_name}__* Hooks[/bold yellow] ({len(hooks)} found)',
                box=box.ROUNDED,
                show_header=True,
                header_style='bold magenta',
            )
            table.add_column('Plugin', style='cyan', width=20)
            table.add_column('Hook Name', style='green')
            table.add_column('BG', justify='center', width=4)
            table.add_column('Type', justify='center', width=5)

            # Sort lexicographically by hook name
            sorted_hooks = sorted(hook_infos, key=lambda h: h['name'])

            for hook in sorted_hooks:
                bg_marker = '[yellow]bg[/yellow]' if hook['is_background'] else ''
                ext = hook['extension'].lstrip('.')
                table.add_row(
                    hook['plugin'],
                    hook['name'],
                    bg_marker,
                    ext,
                )

            prnt(table)
            prnt()
            prnt(f'[dim]{info["description"]}[/dim]')
            prnt()

    # Summary
    if not quiet:
        total_hooks = sum(m['hook_count'] for m in result['models'].values())
        prnt(f'[bold]Total hooks discovered: {total_hooks}[/bold]')
        prnt()
        prnt('[dim]Hook naming convention: on_{Model}__{XX}_{description}[.bg].{ext}[/dim]')
        prnt('[dim]  - XX: Two-digit lexicographic order (00-99)[/dim]')
        prnt('[dim]  - .bg: Background hook (non-blocking)[/dim]')
        prnt('[dim]  - ext: py, sh, or js[/dim]')
        prnt()

    return result


@click.command()
@click.option('--show-disabled', '-a', is_flag=True, help='Show hooks from disabled plugins too')
@click.option('--model', '-m', type=str, default=None, help='Filter to specific model (Crawl, Snapshot, Binary, CrawlEnd)')
@click.option('--quiet', '-q', is_flag=True, help='Output JSON only, no ASCII diagrams')
@docstring(pluginmap.__doc__)
def main(**kwargs):
    import json
    result = pluginmap(**kwargs)
    if kwargs.get('quiet'):
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
