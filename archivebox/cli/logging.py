__package__ = 'archivebox.cli'

import re
import os
import sys
import time
import argparse

from datetime import datetime
from dataclasses import dataclass
from multiprocessing import Process
from typing import Optional, List, Dict, Union, IO

from ..index.schema import Link, ArchiveResult
from ..index.json import to_json
from ..index.csv import links_to_csv
from ..util import enforce_types
from ..config import (
    ConfigDict,
    PYTHON_ENCODING,
    ANSI,
    IS_TTY,
    SHOW_PROGRESS,
    TERM_WIDTH,
    OUTPUT_DIR,
    HTML_INDEX_FILENAME,
    stderr,
)


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



class SmartFormatter(argparse.HelpFormatter):
    """Patched formatter that prints newlines in argparse help strings"""
    def _split_lines(self, text, width):
        if '\n' in text:
            return text.splitlines()
        return argparse.HelpFormatter._split_lines(self, text, width)


def reject_stdin(caller: str, stdin: Optional[IO]=sys.stdin) -> None:
    """Tell the user they passed stdin to a command that doesn't accept it"""

    if stdin and not stdin.isatty():
        stdin_raw_text = stdin.read().strip()
        if stdin_raw_text:
            stderr(f'[X] The "{caller}" command does not accept stdin.', color='red')
            stderr(f'    Run archivebox "{caller} --help" to see usage and examples.')
            stderr()
            raise SystemExit(1)


def accept_stdin(stdin: Optional[IO]=sys.stdin) -> Optional[str]:
    """accept any standard input and return it as a string or None"""
    if not stdin:
        return None
    elif stdin and not stdin.isatty():
        stdin_str = stdin.read().strip()
        return stdin_str or None
    return None


class TimedProgress:
    """Show a progress bar and measure elapsed time until .end() is called"""

    def __init__(self, seconds, prefix=''):
        if SHOW_PROGRESS:
            self.p = Process(target=progress_bar, args=(seconds, prefix))
            self.p.start()

        self.stats = {'start_ts': datetime.now(), 'end_ts': None}

    def end(self):
        """immediately end progress, clear the progressbar line, and save end_ts"""

        end_ts = datetime.now()
        self.stats['end_ts'] = end_ts
        
        if SHOW_PROGRESS:
            # terminate if we havent already terminated
            if self.p is not None:
                self.p.terminate()
                self.p = None

            # clear whole terminal line
            try:
                sys.stdout.write('\r{}{}\r'.format((' ' * TERM_WIDTH()), ANSI['reset']))
            except (IOError, BrokenPipeError):
                # ignore when the parent proc has stopped listening to our stdout
                pass


@enforce_types
def progress_bar(seconds: int, prefix: str='') -> None:
    """show timer in the form of progress bar, with percentage and seconds remaining"""
    chunk = '█' if PYTHON_ENCODING == 'UTF-8' else '#'
    chunks = TERM_WIDTH() - len(prefix) - 20  # number of progress chunks to show (aka max bar width)
    try:
        for s in range(seconds * chunks):
            chunks = TERM_WIDTH() - len(prefix) - 20
            progress = s / chunks / seconds * 100
            bar_width = round(progress/(100/chunks))

            # ████████████████████           0.9% (1/60sec)
            sys.stdout.write('\r{0}{1}{2}{3} {4}% ({5}/{6}sec)'.format(
                prefix,
                ANSI['green'],
                (chunk * bar_width).ljust(chunks),
                ANSI['reset'],
                round(progress, 1),
                round(s/chunks),
                seconds,
            ))
            sys.stdout.flush()
            time.sleep(1 / chunks)

        # ██████████████████████████████████ 100.0% (60/60sec)
        sys.stdout.write('\r{0}{1}{2}{3} {4}% ({5}/{6}sec)\n'.format(
            prefix,
            ANSI['red'],
            chunk * chunks,
            ANSI['reset'],
            100.0,
            seconds,
            seconds,
        ))
        sys.stdout.flush()
    except KeyboardInterrupt:
        print()
        pass


### Parsing Stage

def log_parsing_started(source_file: str):
    start_ts = datetime.now()
    _LAST_RUN_STATS.parse_start_ts = start_ts
    print('\n{green}[*] [{}] Parsing new links from output/sources/{}...{reset}'.format(
        start_ts.strftime('%Y-%m-%d %H:%M:%S'),
        source_file.rsplit('/', 1)[-1],
        **ANSI,
    ))


def log_parsing_finished(num_parsed: int, num_new_links: int, parser_name: str):
    end_ts = datetime.now()
    _LAST_RUN_STATS.parse_end_ts = end_ts
    print('    > Parsed {} links as {} ({} new links added)'.format(num_parsed, parser_name, num_new_links))


### Indexing Stage

def log_indexing_process_started(num_links: int):
    start_ts = datetime.now()
    _LAST_RUN_STATS.index_start_ts = start_ts
    print()
    print('{green}[*] [{}] Writing {} links to main index...{reset}'.format(
        start_ts.strftime('%Y-%m-%d %H:%M:%S'),
        num_links,
        **ANSI,
    ))


def log_indexing_process_finished():
    end_ts = datetime.now()
    _LAST_RUN_STATS.index_end_ts = end_ts


def log_indexing_started(out_path: str):
    if IS_TTY:
        sys.stdout.write(f'    > {out_path}')


def log_indexing_finished(out_path: str):
    print(f'\r    √ {out_path}')


### Archiving Stage

def log_archiving_started(num_links: int, resume: Optional[float]=None):
    start_ts = datetime.now()
    _LAST_RUN_STATS.archiving_start_ts = start_ts
    print()
    if resume:
        print('{green}[▶] [{}] Resuming archive updating for {} pages starting from {}...{reset}'.format(
             start_ts.strftime('%Y-%m-%d %H:%M:%S'),
             num_links,
             resume,
             **ANSI,
        ))
    else:
        print('{green}[▶] [{}] Updating content for {} matching pages in archive...{reset}'.format(
             start_ts.strftime('%Y-%m-%d %H:%M:%S'),
             num_links,
             **ANSI,
        ))

def log_archiving_paused(num_links: int, idx: int, timestamp: str):
    end_ts = datetime.now()
    _LAST_RUN_STATS.archiving_end_ts = end_ts
    print()
    print('\n{lightyellow}[X] [{now}] Downloading paused on link {timestamp} ({idx}/{total}){reset}'.format(
        **ANSI,
        now=end_ts.strftime('%Y-%m-%d %H:%M:%S'),
        idx=idx+1,
        timestamp=timestamp,
        total=num_links,
    ))
    print()
    print('    {lightred}Hint:{reset} To view your archive index, open:'.format(**ANSI))
    print('        {}/{}'.format(OUTPUT_DIR, HTML_INDEX_FILENAME))
    print('    Continue archiving where you left off by running:')
    print('        archivebox update --resume={}'.format(timestamp))

def log_archiving_finished(num_links: int):
    end_ts = datetime.now()
    _LAST_RUN_STATS.archiving_end_ts = end_ts
    assert _LAST_RUN_STATS.archiving_start_ts is not None
    seconds = end_ts.timestamp() - _LAST_RUN_STATS.archiving_start_ts.timestamp()
    if seconds > 60:
        duration = '{0:.2f} min'.format(seconds / 60, 2)
    else:
        duration = '{0:.2f} sec'.format(seconds, 2)

    print()
    print('{}[√] [{}] Update of {} pages complete ({}){}'.format(
        ANSI['green'],
        end_ts.strftime('%Y-%m-%d %H:%M:%S'),
        num_links,
        duration,
        ANSI['reset'],
    ))
    print('    - {} links skipped'.format(_LAST_RUN_STATS.skipped))
    print('    - {} links updated'.format(_LAST_RUN_STATS.succeeded))
    print('    - {} links had errors'.format(_LAST_RUN_STATS.failed))
    print()
    print('    {lightred}Hint:{reset} To view your archive index, open:'.format(**ANSI))
    print('        {}/{}'.format(OUTPUT_DIR, HTML_INDEX_FILENAME))
    print('    Or run the built-in webserver:')
    print('        archivebox server')


def log_link_archiving_started(link: Link, link_dir: str, is_new: bool):
    # [*] [2019-03-22 13:46:45] "Log Structured Merge Trees - ben stopford"
    #     http://www.benstopford.com/2015/02/14/log-structured-merge-trees/
    #     > output/archive/1478739709

    print('\n[{symbol_color}{symbol}{reset}] [{symbol_color}{now}{reset}] "{title}"'.format(
        symbol_color=ANSI['green' if is_new else 'black'],
        symbol='+' if is_new else '√',
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        title=link.title or link.base_url,
        **ANSI,
    ))
    print('    {blue}{url}{reset}'.format(url=link.url, **ANSI))
    print('    {} {}'.format(
        '>' if is_new else '√',
        pretty_path(link_dir),
    ))

def log_link_archiving_finished(link: Link, link_dir: str, is_new: bool, stats: dict):
    total = sum(stats.values())

    if stats['failed'] > 0 :
        _LAST_RUN_STATS.failed += 1
    elif stats['skipped'] == total:
        _LAST_RUN_STATS.skipped += 1
    else:
        _LAST_RUN_STATS.succeeded += 1


def log_archive_method_started(method: str):
    print('      > {}'.format(method))


def log_archive_method_finished(result: ArchiveResult):
    """quote the argument with whitespace in a command so the user can 
       copy-paste the outputted string directly to run the cmd
    """
    # Prettify CMD string and make it safe to copy-paste by quoting arguments
    quoted_cmd = ' '.join(
        '"{}"'.format(arg) if ' ' in arg else arg
        for arg in result.cmd
    )

    if result.status == 'failed':
        # Prettify error output hints string and limit to five lines
        hints = getattr(result.output, 'hints', None) or ()
        if hints:
            hints = hints if isinstance(hints, (list, tuple)) else hints.split('\n')
            hints = (
                '    {}{}{}'.format(ANSI['lightyellow'], line.strip(), ANSI['reset'])
                for line in hints[:5] if line.strip()
            )

        # Collect and prefix output lines with indentation
        output_lines = [
            '{lightred}Failed:{reset}'.format(**ANSI),
            '    {reset}{} {red}{}{reset}'.format(
                result.output.__class__.__name__.replace('ArchiveError', ''),
                result.output, 
                **ANSI,
            ),
            *hints,
            '{}Run to see full output:{}'.format(ANSI['lightred'], ANSI['reset']),
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
    print('{green}[*] Finding links in the archive index matching these {} patterns:{reset}'.format(
        filter_type,
        **ANSI,
    ))
    print('    {}'.format(' '.join(filter_patterns or ())))

def log_list_finished(links):
    print()
    print('---------------------------------------------------------------------------------------------------')
    print(links_to_csv(links, cols=['timestamp', 'is_archived', 'num_outputs', 'url'], header=True, ljust=16, separator=' | '))
    print('---------------------------------------------------------------------------------------------------')
    print()


def log_removal_started(links: List[Link], yes: bool, delete: bool):
    print('{lightyellow}[i] Found {} matching URLs to remove.{reset}'.format(len(links), **ANSI))
    if delete:
        file_counts = [link.num_outputs for link in links if os.path.exists(link.link_dir)]
        print(
            f'    {len(links)} Links will be de-listed from the main index, and their archived content folders will be deleted from disk.\n'
            f'    ({len(file_counts)} data folders with {sum(file_counts)} archived files will be deleted!)'
        )
    else:
        print(
            f'    Matching links will be de-listed from the main index, but their archived content folders will remain in place on disk.\n'
            f'    (Pass --delete if you also want to permanently delete the data folders)'
        )

    if not yes:
        print()
        print('{lightyellow}[?] Do you want to proceed with removing these {} links?{reset}'.format(len(links), **ANSI))
        try:
            assert input('    y/[n]: ').lower() == 'y'
        except (KeyboardInterrupt, EOFError, AssertionError):
            raise SystemExit(0)

def log_removal_finished(all_links: int, to_keep: int):
    if all_links == 0:
        print()
        print('{red}[X] No matching links found.{reset}'.format(**ANSI))
    else:
        num_removed = all_links - to_keep
        print()
        print('{red}[√] Removed {} out of {} links from the archive index.{reset}'.format(
            num_removed,
            all_links,
            **ANSI,
        ))
        print('    Index now contains {} links.'.format(to_keep))


def log_shell_welcome_msg():
    from . import list_subcommands

    print('{green}# ArchiveBox Imports{reset}'.format(**ANSI))
    print('{green}from archivebox.core.models import Snapshot, User{reset}'.format(**ANSI))
    print('{green}from archivebox import *\n    {}{reset}'.format("\n    ".join(list_subcommands().keys()), **ANSI))
    print()
    print('[i] Welcome to the ArchiveBox Shell!')
    print('    https://github.com/pirate/ArchiveBox/wiki/Usage#Shell-Usage')
    print()
    print('    {lightred}Hint:{reset} Example use:'.format(**ANSI))
    print('        print(Snapshot.objects.filter(is_archived=True).count())')
    print('        Snapshot.objects.get(url="https://example.com").as_json()')
    print('        add("https://example.com/some/new/url")')



### Helpers

@enforce_types
def pretty_path(path: str) -> str:
    """convert paths like .../ArchiveBox/archivebox/../output/abc into output/abc"""
    pwd = os.path.abspath('.')
    # parent = os.path.abspath(os.path.join(pwd, os.path.pardir))
    return path.replace(pwd + '/', './')


@enforce_types
def printable_filesize(num_bytes: Union[int, float]) -> str:
    for count in ['Bytes','KB','MB','GB']:
        if num_bytes > -1024.0 and num_bytes < 1024.0:
            return '%3.1f %s' % (num_bytes, count)
        num_bytes /= 1024.0
    return '%3.1f %s' % (num_bytes, 'TB')


@enforce_types
def printable_folders(folders: Dict[str, Optional[Link]],
                      json: bool=False,
                      csv: Optional[str]=None) -> str:
    if json: 
        return to_json(folders.values(), indent=4, sort_keys=True)

    elif csv:
        return links_to_csv(folders.values(), cols=csv.split(','), header=True)
    
    return '\n'.join(f'{folder} {link}' for folder, link in folders.items())



@enforce_types
def printable_config(config: ConfigDict, prefix: str='') -> str:
    return f'\n{prefix}'.join(
        f'{key}={val}'
        for key, val in config.items()
        if not (isinstance(val, dict) or callable(val))
    )


@enforce_types
def printable_folder_status(name: str, folder: Dict) -> str:
    if folder['enabled']:
        if folder['is_valid']:
            color, symbol, note = 'green', '√', 'valid'
        else:
            color, symbol, note, num_files = 'red', 'X', 'invalid', '?'
    else:
        color, symbol, note, num_files = 'lightyellow', '-', 'disabled', '-'

    if folder['path']:
        if os.path.exists(folder['path']):
            num_files = (
                f'{len(os.listdir(folder["path"]))} files'
                if os.path.isdir(folder['path']) else
                printable_filesize(os.path.getsize(folder['path']))
            )
        else:
            num_files = 'missing'

        if ' ' in folder['path']:
            folder['path'] = f'"{folder["path"]}"'

    return ' '.join((
        ANSI[color],
        symbol,
        ANSI['reset'],
        name.ljust(22),
        (folder["path"] or '').ljust(76),
        num_files.ljust(14),
        ANSI[color],
        note,
        ANSI['reset'],
    ))


@enforce_types
def printable_dependency_version(name: str, dependency: Dict) -> str:
    if dependency['enabled']:
        if dependency['is_valid']:
            color, symbol, note, version = 'green', '√', 'valid', ''

            parsed_version_num = re.search(r'[\d\.]+', dependency['version'])
            if parsed_version_num:
                version = f'v{parsed_version_num[0]}'

        if not version:
            color, symbol, note, version = 'red', 'X', 'invalid', '?'
    else:
        color, symbol, note, version = 'lightyellow', '-', 'disabled', '-'

    if ' ' in dependency["path"]:
        dependency["path"] = f'"{dependency["path"]}"'

    return ' '.join((
        ANSI[color],
        symbol,
        ANSI['reset'],
        name.ljust(22),
        (dependency["path"] or '').ljust(76),
        version.ljust(14),
        ANSI[color],
        note,
        ANSI['reset'],
    ))
