__package__ = 'archivebox'

# High-level logging functions for CLI output and progress tracking
# Low-level primitives (Rich console, ANSI colors) are in logging.py

import re
import os
import sys
import time

from math import log
from multiprocessing import Process
from pathlib import Path

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Optional, List, Dict, Union, Iterable, IO, TYPE_CHECKING

if TYPE_CHECKING:
    from archivebox.core.models import Snapshot

from rich import print
from rich.panel import Panel
from django.core.management.base import DjangoHelpFormatter

from archivebox.config import CONSTANTS, DATA_DIR, VERSION
from archivebox.config.common import SHELL_CONFIG
from archivebox.misc.system import get_dir_size
from archivebox.misc.util import enforce_types
from archivebox.misc.logging import ANSI, stderr

@dataclass
class RuntimeStats:
    """mutable stats counter for logging archiving timing info to CLI output"""

    skipped: int = 0
    succeeded: int = 0
    failed: int = 0

    parse_start_ts: Optional[datetime] = None
    parse_end_ts: Optional[datetime] = None

    index_start_ts: Optional[datetime] = None
    index_end_ts: Optional[datetime] = None

    archiving_start_ts: Optional[datetime] = None
    archiving_end_ts: Optional[datetime] = None

# globals are bad, mmkay
_LAST_RUN_STATS = RuntimeStats()


class TimedProgress:
    """Show a progress bar and measure elapsed time until .end() is called"""

    def __init__(self, seconds, prefix=''):

        self.SHOW_PROGRESS = SHELL_CONFIG.SHOW_PROGRESS
        self.ANSI = SHELL_CONFIG.ANSI
        
        if self.SHOW_PROGRESS:
            self.p = Process(target=progress_bar, args=(seconds, prefix, self.ANSI))
            self.p.start()

        self.stats = {'start_ts': datetime.now(timezone.utc), 'end_ts': None}

    def end(self):
        """immediately end progress, clear the progressbar line, and save end_ts"""


        end_ts = datetime.now(timezone.utc)
        self.stats['end_ts'] = end_ts
        
        if self.SHOW_PROGRESS:
            # terminate if we havent already terminated
            try:
                # kill the progress bar subprocess
                try:
                    self.p.close()   # must be closed *before* its terminnated
                except (KeyboardInterrupt, SystemExit):
                    print()
                    raise
                except BaseException:                                           # lgtm [py/catch-base-exception]
                    pass
                self.p.terminate()
                time.sleep(0.1)
                # sometimes the timer doesn't terminate properly, then blocks at the join until
                # the full time has elapsed. sending a kill tries to avoid that.
                try:
                    self.p.kill() 
                except Exception:
                    pass


                # clear whole terminal line
                try:
                    sys.stdout.write('\r{}{}\r'.format((' ' * SHELL_CONFIG.TERM_WIDTH), self.ANSI['reset']))
                except (IOError, BrokenPipeError):
                    # ignore when the parent proc has stopped listening to our stdout
                    pass
            except ValueError:
                pass


@enforce_types
def progress_bar(seconds: int, prefix: str='', ANSI: Dict[str, str]=ANSI) -> None:
    """show timer in the form of progress bar, with percentage and seconds remaining"""
    output_buf = (sys.stdout or sys.__stdout__ or sys.stderr or sys.__stderr__)
    chunk = '█' if output_buf and output_buf.encoding.upper() == 'UTF-8' else '#'
    last_width = SHELL_CONFIG.TERM_WIDTH
    chunks = last_width - len(prefix) - 20  # number of progress chunks to show (aka max bar width)
    try:
        for s in range(seconds * chunks):
            max_width = SHELL_CONFIG.TERM_WIDTH
            if max_width < last_width:
                # when the terminal size is shrunk, we have to write a newline
                # otherwise the progress bar will keep wrapping incorrectly
                sys.stdout.write('\r\n')
                sys.stdout.flush()
            chunks = max_width - len(prefix) - 20
            pct_complete = s / chunks / seconds * 100
            log_pct = (log(pct_complete or 1, 10) / 2) * 100  # everyone likes faster progress bars ;)
            bar_width = round(log_pct/(100/chunks))
            last_width = max_width

            # ████████████████████           0.9% (1/60sec)
            sys.stdout.write('\r{0}{1}{2}{3} {4}% ({5}/{6}sec)'.format(
                prefix,
                ANSI['green' if pct_complete < 80 else 'lightyellow'],
                (chunk * bar_width).ljust(chunks),
                ANSI['reset'],
                round(pct_complete, 1),
                round(s/chunks),
                seconds,
            ))
            sys.stdout.flush()
            time.sleep(1 / chunks)

        # ██████████████████████████████████ 100.0% (60/60sec)
        sys.stdout.write('\r{0}{1}{2}{3} {4}% ({5}/{6}sec)'.format(
            prefix,
            ANSI['red'],
            chunk * chunks,
            ANSI['reset'],
            100.0,
            seconds,
            seconds,
        ))
        sys.stdout.flush()
        # uncomment to have it disappear when it hits 100% instead of staying full red:
        # time.sleep(0.5)
        # sys.stdout.write('\r{}{}\r'.format((' ' * SHELL_CONFIG.TERM_WIDTH), ANSI['reset']))
        # sys.stdout.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        print()


def log_cli_command(subcommand: str, subcommand_args: Iterable[str]=(), stdin: str | IO | None=None, pwd: str='.'):
    args = ' '.join(subcommand_args)
    version_msg = '[dark_magenta]\\[{now}][/dark_magenta] [dark_red]ArchiveBox[/dark_red] [dark_goldenrod]v{VERSION}[/dark_goldenrod]: [green4]archivebox [green3]{subcommand}[green2] {args}[/green2]'.format(
        now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        VERSION=VERSION,
        subcommand=subcommand,
        args=args,
    )
    # stderr()
    # stderr('[bright_black]    > {pwd}[/]'.format(pwd=pwd, **ANSI))
    # stderr()
    print(Panel(version_msg), file=sys.stderr)
    
### Parsing Stage


def log_importing_started(urls: Union[str, List[str]], depth: int, index_only: bool):
    _LAST_RUN_STATS.parse_start_ts = datetime.now(timezone.utc)
    print('[green][+] [{}] Adding {} links to index (crawl depth={}){}...[/]'.format(
        _LAST_RUN_STATS.parse_start_ts.strftime('%Y-%m-%d %H:%M:%S'),
        len(urls) if isinstance(urls, list) else len(urls.split('\n')),
        depth,
        ' (index only)' if index_only else '',
    ))

def log_source_saved(source_file: str):
    print('    > Saved verbatim input to {}/{}'.format(CONSTANTS.SOURCES_DIR_NAME, source_file.rsplit('/', 1)[-1]))

def log_parsing_finished(num_parsed: int, parser_name: str):
    _LAST_RUN_STATS.parse_end_ts = datetime.now(timezone.utc)
    print('    > Parsed {} URLs from input ({})'.format(num_parsed, parser_name))

def log_deduping_finished(num_new_links: int):
    print('    > Found {} new URLs not already in index'.format(num_new_links))


def log_crawl_started(new_links):
    print()
    print(f'[green][*] Starting crawl of {len(new_links)} sites 1 hop out from starting point[/]')

### Indexing Stage

def log_indexing_process_started(num_links: int):
    start_ts = datetime.now(timezone.utc)
    _LAST_RUN_STATS.index_start_ts = start_ts
    print()
    print('[bright_black][*] [{}] Writing {} links to main index...[/]'.format(
        start_ts.strftime('%Y-%m-%d %H:%M:%S'),
        num_links,
    ))


def log_indexing_process_finished():
    end_ts = datetime.now(timezone.utc)
    _LAST_RUN_STATS.index_end_ts = end_ts


def log_indexing_started(out_path: str):
    if SHELL_CONFIG.IS_TTY:
        sys.stdout.write(f'    > ./{Path(out_path).relative_to(DATA_DIR)}')


def log_indexing_finished(out_path: str):
    print(f'\r    √ ./{Path(out_path).relative_to(DATA_DIR)}')


### Archiving Stage

def log_archiving_started(num_links: int, resume: Optional[float]=None):

    start_ts = datetime.now(timezone.utc)
    _LAST_RUN_STATS.archiving_start_ts = start_ts
    print()
    if resume:
        print('[green][▶] [{}] Resuming archive updating for {} pages starting from {}...[/]'.format(
            start_ts.strftime('%Y-%m-%d %H:%M:%S'),
            num_links,
            resume,
        ))
    else:
        print('[green][▶] [{}] Starting archiving of {} snapshots in index...[/]'.format(
            start_ts.strftime('%Y-%m-%d %H:%M:%S'),
            num_links,
        ))

def log_archiving_paused(num_links: int, idx: int, timestamp: str):

    end_ts = datetime.now(timezone.utc)
    _LAST_RUN_STATS.archiving_end_ts = end_ts
    print()
    print('\n[yellow3][X] [{now}] Downloading paused on link {timestamp} ({idx}/{total})[/]'.format(
        now=end_ts.strftime('%Y-%m-%d %H:%M:%S'),
        idx=idx+1,
        timestamp=timestamp,
        total=num_links,
    ))
    print()
    print('    Continue archiving where you left off by running:')
    print('        archivebox update --resume={}'.format(timestamp))

def log_archiving_finished(num_links: int):

    from archivebox.core.models import Snapshot

    end_ts = datetime.now(timezone.utc)
    _LAST_RUN_STATS.archiving_end_ts = end_ts
    assert _LAST_RUN_STATS.archiving_start_ts is not None
    seconds = end_ts.timestamp() - _LAST_RUN_STATS.archiving_start_ts.timestamp()
    if seconds > 60:
        duration = '{0:.2f} min'.format(seconds / 60)
    else:
        duration = '{0:.2f} sec'.format(seconds)

    print()
    print('[green][√] [{}] Update of {} pages complete ({})[/]'.format(
        end_ts.strftime('%Y-%m-%d %H:%M:%S'),
        num_links,
        duration,
    ))
    print('    - {} links skipped'.format(_LAST_RUN_STATS.skipped))
    print('    - {} links updated'.format(_LAST_RUN_STATS.succeeded + _LAST_RUN_STATS.failed))
    print('    - {} links had errors'.format(_LAST_RUN_STATS.failed))
    
    if Snapshot.objects.count() < 50:
        print()
        print('    [violet]Hint:[/] To manage your archive in a Web UI, run:')
        print('        archivebox server 0.0.0.0:8000')


def log_snapshot_archiving_started(snapshot: "Snapshot", out_dir: str, is_new: bool):

    # [*] [2019-03-22 13:46:45] "Log Structured Merge Trees - ben stopford"
    #     http://www.benstopford.com/2015/02/14/log-structured-merge-trees/
    #     > output/archive/1478739709

    print('\n[[{symbol_color}]{symbol}[/]] [[{symbol_color}]{now}[/]] "{title}"'.format(
        symbol_color='green' if is_new else 'bright_black',
        symbol='+' if is_new else '√',
        now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        title=snapshot.title or snapshot.base_url,
    ))
    print(f'    [sky_blue1]{snapshot.url}[/]')
    print('    {} {}'.format(
        '>' if is_new else '√',
        pretty_path(out_dir),
    ))

def log_snapshot_archiving_finished(snapshot: "Snapshot", out_dir: str, is_new: bool, stats: dict, start_ts: datetime):
    total = sum(stats.values())

    if stats['failed'] > 0 :
        _LAST_RUN_STATS.failed += 1
    elif stats['skipped'] == total:
        _LAST_RUN_STATS.skipped += 1
    else:
        _LAST_RUN_STATS.succeeded += 1

    try:
        size = get_dir_size(out_dir)
    except FileNotFoundError:
        size = (0, None, '0')

    end_ts = datetime.now(timezone.utc)
    duration = str(end_ts - start_ts).split('.')[0]
    print('        [bright_black]{} files ({}) in {}s [/]'.format(size[2], printable_filesize(size[0]), duration))



def log_archive_method_started(method: str):
    print('      > {}'.format(method))


def log_archive_method_finished(result: dict):
    """
    quote the argument with whitespace in a command so the user can
    copy-paste the outputted string directly to run the cmd
    """
    # Prettify CMD string and make it safe to copy-paste by quoting arguments
    quoted_cmd = ' '.join(
        '"{}"'.format(arg) if (' ' in arg) or (':' in arg) else arg
        for arg in result['cmd']
    )

    if result['status'] == 'failed':
        output = result.get('output')
        if output and output.__class__.__name__ == 'TimeoutExpired':
            duration = (result['end_ts'] - result['start_ts']).seconds
            hint_header = [
                f'[yellow3]Extractor timed out after {duration}s.[/]',
            ]
        else:
            error_name = output.__class__.__name__.replace('ArchiveError', '') if output else 'Error'
            hint_header = [
                '[yellow3]Extractor failed:[/]',
                f'    {error_name} [red1]{output}[/]',
            ]

        # Prettify error output hints string and limit to five lines
        hints = getattr(output, 'hints', None) or () if output else ()
        if hints:
            if isinstance(hints, (list, tuple, type(_ for _ in ()))):
                hints = [hint.decode() if isinstance(hint, bytes) else str(hint) for hint in hints]
            else:
                if isinstance(hints, bytes):
                    hints = hints.decode()
                hints = hints.split('\n')

            hints = (
                f'    [yellow1]{line.strip()}[/]'
                for line in list(hints)[:5] if line.strip()
            )

        docker_hints = ()
        if os.environ.get('IN_DOCKER') in ('1', 'true', 'True', 'TRUE', 'yes'):
            docker_hints = (
                '  docker run -it -v $PWD/data:/data archivebox/archivebox /bin/bash',
            )

        # Collect and prefix output lines with indentation
        output_lines = [
            *hint_header,
            *hints,
            '[violet]Run to see full output:[/]',
            *docker_hints,
            *(['    cd {};'.format(result.get('pwd'))] if result.get('pwd') else []),
            '    {}'.format(quoted_cmd),
        ]
        print('\n'.join(
            '        {}'.format(line)
            for line in output_lines
            if line
        ))
        print()


def log_list_started(filter_patterns: Optional[List[str]], filter_type: str):
    print(f'[green][*] Finding links in the archive index matching these {filter_type} patterns:[/]')
    print('    {}'.format(' '.join(filter_patterns or ())))

def log_list_finished(snapshots):
    from archivebox.core.models import Snapshot
    print()
    print('---------------------------------------------------------------------------------------------------')
    print(Snapshot.objects.filter(pk__in=[s.pk for s in snapshots]).to_csv(cols=['timestamp', 'is_archived', 'num_outputs', 'url'], header=True, ljust=16, separator=' | '))
    print('---------------------------------------------------------------------------------------------------')
    print()


def log_removal_started(snapshots, yes: bool, delete: bool):
    count = snapshots.count() if hasattr(snapshots, 'count') else len(snapshots)
    print(f'[yellow3][i] Found {count} matching URLs to remove.[/]')
    if delete:
        file_counts = [s.num_outputs for s in snapshots if os.access(s.output_dir, os.R_OK)]
        print(
            f'    {count} Links will be de-listed from the main index, and their archived content folders will be deleted from disk.\n'
            f'    ({len(file_counts)} data folders with {sum(file_counts)} archived files will be deleted!)'
        )
    else:
        print(
            '    Matching links will be de-listed from the main index, but their archived content folders will remain in place on disk.\n'
            '    (Pass --delete if you also want to permanently delete the data folders)'
        )

    if not yes:
        print()
        print(f'[yellow3][?] Do you want to proceed with removing these {count} links?[/]')
        try:
            assert input('    y/[n]: ').lower() == 'y'
        except (KeyboardInterrupt, EOFError, AssertionError):
            raise SystemExit(0)

def log_removal_finished(all_links: int, to_remove: int):
    if all_links == 0:
        print()
        print('[red1][X] No matching links found.[/]')
    else:
        print()
        print(f'[red1][√] Removed {to_remove} out of {all_links} links from the archive index.[/]')
        print(f'    Index now contains {all_links - to_remove} links.')


### Search Indexing Stage

def log_index_started(url: str):
    print('[green][*] Indexing url: {} in the search index[/]'.format(url))
    print()


### Helpers

@enforce_types
def pretty_path(path: Union[Path, str], pwd: Union[Path, str]=DATA_DIR, color: bool=True) -> str:
    """convert paths like .../ArchiveBox/archivebox/../output/abc into output/abc"""
    pwd = str(Path(pwd))  # .resolve()
    path = str(path)

    if not path:
        return path

    # replace long absolute paths with ./ relative ones to save on terminal output width
    if path.startswith(pwd) and (pwd != '/') and path != pwd:
        if color:
            path = path.replace(pwd, '[light_slate_blue].[/light_slate_blue]', 1)
        else:
            path = path.replace(pwd, '.', 1)
    
    # quote paths containing spaces
    if ' ' in path:
        path = f'"{path}"'
        
    # replace home directory with ~ for shorter output
    path = path.replace(str(Path('~').expanduser()), '~')

    return path


@enforce_types
def printable_filesize(num_bytes: Union[int, float]) -> str:
    for count in ['Bytes','KB','MB','GB']:
        if num_bytes > -1024.0 and num_bytes < 1024.0:
            return '%3.1f %s' % (num_bytes, count)
        num_bytes /= 1024.0
    return '%3.1f %s' % (num_bytes, 'TB')


@enforce_types
def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 1:
        return f'{seconds*1000:.0f}ms'
    elif seconds < 60:
        return f'{seconds:.1f}s'
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f'{minutes}min {secs}s' if secs else f'{minutes}min'
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f'{hours}hr {minutes}min' if minutes else f'{hours}hr'


@enforce_types
def truncate_url(url: str, max_length: int = 60) -> str:
    """Truncate URL to max_length, keeping domain and adding ellipsis."""
    if len(url) <= max_length:
        return url
    # Try to keep the domain and beginning of path
    if '://' in url:
        protocol, rest = url.split('://', 1)
        if '/' in rest:
            domain, path = rest.split('/', 1)
            available = max_length - len(protocol) - len(domain) - 6  # for "://", "/", "..."
            if available > 10:
                return f'{protocol}://{domain}/{path[:available]}...'
    # Fallback: just truncate
    return url[:max_length-3] + '...'


@enforce_types
def log_worker_event(
    worker_type: str,
    event: str,
    indent_level: int = 0,
    pid: Optional[int] = None,
    worker_id: Optional[str] = None,
    url: Optional[str] = None,
    plugin: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    error: Optional[Exception] = None,
) -> None:
    """
    Log a worker event with structured metadata and indentation.

    Args:
        worker_type: Type of worker (Orchestrator, CrawlWorker, SnapshotWorker)
        event: Event name (Starting, Completed, Failed, etc.)
        indent_level: Indentation level (0=Orchestrator, 1=CrawlWorker, 2=SnapshotWorker)
        pid: Process ID
        worker_id: Worker ID (UUID for workers)
        url: URL being processed (for SnapshotWorker)
        plugin: Plugin name (for hook processes)
        metadata: Dict of metadata to show in curly braces
        error: Exception if event is an error
    """
    indent = '    ' * indent_level

    from rich.markup import escape

    # Build worker identifier (without URL/plugin)
    worker_parts = [worker_type]
    # Don't add pid/worker_id for DB operations (they happen in whatever process is running)
    if pid and worker_type != 'DB':
        worker_parts.append(f'pid={pid}')
    if worker_id and worker_type in ('CrawlWorker', 'Orchestrator') and worker_type != 'DB':
        worker_parts.append(f'id={worker_id}')

    # Build worker label parts for brackets (shown inside brackets)
    worker_label_base = worker_parts[0]
    worker_bracket_content = ", ".join(worker_parts[1:]) if len(worker_parts) > 1 else None

    # Build URL/plugin display (shown AFTER the label, outside brackets)
    url_extractor_parts = []
    if url:
        url_extractor_parts.append(f'url: {escape(url)}')
    if plugin:
        url_extractor_parts.append(f'extractor: {escape(plugin)}')

    url_extractor_str = ' | '.join(url_extractor_parts) if url_extractor_parts else ''

    # Build metadata string
    metadata_str = ''
    if metadata:
        # Format metadata nicely
        meta_parts = []
        for k, v in metadata.items():
            if isinstance(v, float):
                # Format floats nicely (durations, sizes)
                if 'duration' in k.lower():
                    meta_parts.append(f'{k}: {format_duration(v)}')
                elif 'size' in k.lower():
                    meta_parts.append(f'{k}: {printable_filesize(int(v))}')
                else:
                    meta_parts.append(f'{k}: {v:.2f}')
            elif isinstance(v, int):
                # Format integers - check if it's a size
                if 'size' in k.lower() or 'bytes' in k.lower():
                    meta_parts.append(f'{k}: {printable_filesize(v)}')
                else:
                    meta_parts.append(f'{k}: {v}')
            elif isinstance(v, (list, tuple)):
                meta_parts.append(f'{k}: {len(v)}')
            else:
                meta_parts.append(f'{k}: {v}')
        metadata_str = ' | '.join(meta_parts)

    # Determine color based on event
    color = 'white'
    if event in ('Starting...', 'Started', 'STARTED', 'Started in background'):
        color = 'green'
    elif event.startswith('Created'):
        color = 'cyan'  # DB creation events
    elif event in ('Completed', 'COMPLETED', 'All work complete'):
        color = 'blue'
    elif event in ('Failed', 'ERROR', 'Failed to spawn worker'):
        color = 'red'
    elif event in ('Shutting down', 'SHUTDOWN'):
        color = 'grey53'

    # Build final message
    error_str = f' {type(error).__name__}: {error}' if error else ''
    from archivebox.misc.logging import CONSOLE
    from rich.text import Text

    # Create a Rich Text object for proper formatting
    # Text.append() treats content as literal (no markup parsing)
    text = Text()
    text.append(indent)
    text.append(worker_label_base, style=color)

    # Add bracketed content if present (using Text.append to avoid markup issues)
    if worker_bracket_content:
        text.append('[', style=color)
        text.append(worker_bracket_content, style=color)
        text.append(']', style=color)

    text.append(f' {event}{error_str}', style=color)

    # Add URL/plugin info first (more important)
    if url_extractor_str:
        text.append(f' | {url_extractor_str}')

    # Then add other metadata
    if metadata_str:
        text.append(f' | {metadata_str}')

    CONSOLE.print(text, soft_wrap=True)


@enforce_types
def printable_folders(folders: Dict[str, Optional["Snapshot"]], with_headers: bool=False) -> str:
    return '\n'.join(
        f'{folder} {snapshot and snapshot.url} "{snapshot and snapshot.title}"'
        for folder, snapshot in folders.items()
    )



@enforce_types
def printable_config(config: dict, prefix: str='') -> str:
    return f'\n{prefix}'.join(
        f'{key}={val}'
        for key, val in config.items()
        if not (isinstance(val, dict) or callable(val))
    )


@enforce_types
def printable_folder_status(name: str, folder: Dict) -> str:
    if folder['enabled']:
        if folder['is_valid']:
            color, symbol, note, num_files = 'green', '√', 'valid', ''
        else:
            color, symbol, note, num_files = 'red', 'X', 'invalid', '?'
    else:
        color, symbol, note, num_files = 'grey53', '-', 'unused', '-'


    if folder['path']:
        if os.access(folder['path'], os.R_OK):
            try:
                num_files = (
                    f'{len(os.listdir(folder["path"]))} files'
                    if os.path.isdir(folder['path']) else
                    printable_filesize(Path(folder['path']).stat().st_size)
                )
            except PermissionError:
                num_files = 'error'
        else:
            num_files = 'missing'
        
    if folder.get('is_mount'):
        # add symbol @ next to filecount if path is a remote filesystem mount
        num_files = f'{num_files} @' if num_files else '@'

    path = pretty_path(folder['path'])

    return ' '.join((
        f'[{color}]',
        symbol,
        '[/]',
        name.ljust(21).replace('DATA_DIR', '[light_slate_blue]DATA_DIR[/light_slate_blue]'),
        num_files.ljust(14).replace('missing', '[grey53]missing[/grey53]'),
        f'[{color}]',
        note.ljust(8),
        '[/]',
        path.ljust(76),
    ))


@enforce_types
def printable_dependency_version(name: str, dependency: Dict) -> str:
    color, symbol, note, version = 'red', 'X', 'invalid', '?'

    if dependency['enabled']:
        if dependency['is_valid']:
            color, symbol, note = 'green', '√', 'valid'

            parsed_version_num = re.search(r'[\d\.]+', dependency['version'])
            if parsed_version_num:
                version = f'v{parsed_version_num[0]}'
    else:
        color, symbol, note, version = 'lightyellow', '-', 'disabled', '-'

    path = pretty_path(dependency['path'])

    return ' '.join((
        ANSI[color],
        symbol,
        ANSI['reset'],
        name.ljust(21),
        version.ljust(14),
        ANSI[color],
        note.ljust(8),
        ANSI['reset'],
        path.ljust(76),
    ))
