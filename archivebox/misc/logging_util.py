__package__ = 'archivebox'

import re
import os
import sys
import stat
import time

from math import log
from multiprocessing import Process
from pathlib import Path

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Optional, List, Dict, Union, Iterable, IO, TYPE_CHECKING

if TYPE_CHECKING:
    from ..index.schema import Link, ArchiveResult

from rich import print
from rich.panel import Panel
from rich_argparse import RichHelpFormatter
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


def debug_dict_summary(obj: Dict[Any, Any]) -> None:
    stderr(' '.join(f'{key}={str(val).ljust(6)}' for key, val in obj.items()))


def get_fd_info(fd) -> Dict[str, Any]:
    NAME = fd.name[1:-1]
    FILENO = fd.fileno()
    MODE = os.fstat(FILENO).st_mode
    IS_TTY = hasattr(fd, 'isatty') and fd.isatty()
    IS_PIPE = stat.S_ISFIFO(MODE)
    IS_FILE = stat.S_ISREG(MODE)
    IS_TERMINAL =  not (IS_PIPE or IS_FILE)
    IS_LINE_BUFFERED = fd.line_buffering
    IS_READABLE = fd.readable()
    return {
        'NAME': NAME, 'FILENO': FILENO, 'MODE': MODE,
        'IS_TTY': IS_TTY, 'IS_PIPE': IS_PIPE, 'IS_FILE': IS_FILE,
        'IS_TERMINAL': IS_TERMINAL, 'IS_LINE_BUFFERED': IS_LINE_BUFFERED,
        'IS_READABLE': IS_READABLE,
    }
    

# # Log debug information about stdin, stdout, and stderr
# sys.stdout.write('[>&1] this is python stdout\n')
# sys.stderr.write('[>&2] this is python stderr\n')

# debug_dict_summary(get_fd_info(sys.stdin))
# debug_dict_summary(get_fd_info(sys.stdout))
# debug_dict_summary(get_fd_info(sys.stderr))



class SmartFormatter(DjangoHelpFormatter, RichHelpFormatter):
    """Patched formatter that prints newlines in argparse help strings"""
    def _split_lines(self, text, width):
        if '\n' in text:
            return text.splitlines()
        return RichHelpFormatter._split_lines(self, text, width)


def reject_stdin(caller: str, stdin: Optional[IO]=sys.stdin) -> None:
    """Tell the user they passed stdin to a command that doesn't accept it"""

    if not stdin:
        return None

    if os.environ.get('IN_DOCKER') in ('1', 'true', 'True', 'TRUE', 'yes'):
        # when TTY is disabled in docker we cant tell if stdin is being piped in or not
        # if we try to read stdin when its not piped we will hang indefinitely waiting for it
        return None

    if not stdin.isatty():
        # stderr('READING STDIN TO REJECT...')
        stdin_raw_text = stdin.read()
        if stdin_raw_text.strip():
            # stderr('GOT STDIN!', len(stdin_str))
            stderr(f'[!] The "{caller}" command does not accept stdin (ignoring).', color='red')
            stderr(f'    Run archivebox "{caller} --help" to see usage and examples.')
            stderr()
            # raise SystemExit(1)
    return None


def accept_stdin(stdin: Optional[IO]=sys.stdin) -> Optional[str]:
    """accept any standard input and return it as a string or None"""
    
    if not stdin:
        return None

    if not stdin.isatty():
        # stderr('READING STDIN TO ACCEPT...')
        stdin_str = stdin.read()

        if stdin_str:
            # stderr('GOT STDIN...', len(stdin_str))
            return stdin_str

    return None


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
                self.p.join()


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

    from core.models import Snapshot

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


def log_link_archiving_started(link: "Link", link_dir: str, is_new: bool):

    # [*] [2019-03-22 13:46:45] "Log Structured Merge Trees - ben stopford"
    #     http://www.benstopford.com/2015/02/14/log-structured-merge-trees/
    #     > output/archive/1478739709

    print('\n[[{symbol_color}]{symbol}[/]] [[{symbol_color}]{now}[/]] "{title}"'.format(
        symbol_color='green' if is_new else 'bright_black',
        symbol='+' if is_new else '√',
        now=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        title=link.title or link.base_url,
    ))
    print(f'    [sky_blue1]{link.url}[/]')
    print('    {} {}'.format(
        '>' if is_new else '√',
        pretty_path(link_dir),
    ))

def log_link_archiving_finished(link: "Link", link_dir: str, is_new: bool, stats: dict, start_ts: datetime):
    total = sum(stats.values())

    if stats['failed'] > 0 :
        _LAST_RUN_STATS.failed += 1
    elif stats['skipped'] == total:
        _LAST_RUN_STATS.skipped += 1
    else:
        _LAST_RUN_STATS.succeeded += 1

    try:
        size = get_dir_size(link_dir)
    except FileNotFoundError:
        size = (0, None, '0')

    end_ts = datetime.now(timezone.utc)
    duration = str(end_ts - start_ts).split('.')[0]
    print('        [bright_black]{} files ({}) in {}s [/]'.format(size[2], printable_filesize(size[0]), duration))


def log_archive_method_started(method: str):
    print('      > {}'.format(method))


def log_archive_method_finished(result: "ArchiveResult"):
    """
    quote the argument with whitespace in a command so the user can 
    copy-paste the outputted string directly to run the cmd
    """
    # Prettify CMD string and make it safe to copy-paste by quoting arguments
    quoted_cmd = ' '.join(
        '"{}"'.format(arg) if (' ' in arg) or (':' in arg) else arg
        for arg in result.cmd
    )

    if result.status == 'failed':
        if result.output.__class__.__name__ == 'TimeoutExpired':
            duration = (result.end_ts - result.start_ts).seconds
            hint_header = [
                f'[yellow3]Extractor timed out after {duration}s.[/]',
            ]
        else:
            error_name = result.output.__class__.__name__.replace('ArchiveError', '')
            hint_header = [
                '[yellow3]Extractor failed:[/]',
                f'    {error_name} [red1]{result.output}[/]',
            ]
        
        # import pudb; pudb.set_trace()

        # Prettify error output hints string and limit to five lines
        hints = getattr(result.output, 'hints', None) or ()
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
            *(['    cd {};'.format(result.pwd)] if result.pwd else []),
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

def log_list_finished(links):
    from archivebox.index.csv import links_to_csv
    print()
    print('---------------------------------------------------------------------------------------------------')
    print(links_to_csv(links, cols=['timestamp', 'is_archived', 'num_outputs', 'url'], header=True, ljust=16, separator=' | '))
    print('---------------------------------------------------------------------------------------------------')
    print()


def log_removal_started(links: List["Link"], yes: bool, delete: bool):
    print(f'[yellow3][i] Found {len(links)} matching URLs to remove.[/]')
    if delete:
        file_counts = [link.num_outputs for link in links if os.access(link.link_dir, os.R_OK)]
        print(
            f'    {len(links)} Links will be de-listed from the main index, and their archived content folders will be deleted from disk.\n'
            f'    ({len(file_counts)} data folders with {sum(file_counts)} archived files will be deleted!)'
        )
    else:
        print(
            '    Matching links will be de-listed from the main index, but their archived content folders will remain in place on disk.\n'
            '    (Pass --delete if you also want to permanently delete the data folders)'
        )

    if not yes:
        print()
        print(f'[yellow3][?] Do you want to proceed with removing these {len(links)} links?[/]')
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
def printable_folders(folders: Dict[str, Optional["Link"]], with_headers: bool=False) -> str:
    return '\n'.join(
        f'{folder} {link and link.url} "{link and link.title}"'
        for folder, link in folders.items()
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
