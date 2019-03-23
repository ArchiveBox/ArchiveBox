import sys
from datetime import datetime
from config import ANSI, REPO_DIR, OUTPUT_DIR


# globals are bad, mmkay
_LAST_RUN_STATS = {
    'skipped': 0,
    'succeeded': 0,
    'failed': 0,

    'parsing_start_ts': 0,
    'parsing_end_ts': 0,

    'indexing_start_ts': 0,
    'indexing_end_ts': 0,

    'archiving_start_ts': 0,
    'archiving_end_ts': 0,

    'links': {},
}

def pretty_path(path):
    """convert paths like .../ArchiveBox/archivebox/../output/abc into output/abc"""
    return path.replace(REPO_DIR + '/', '')


### Parsing Stage

def log_parsing_started(source_file):
    start_ts = datetime.now()
    _LAST_RUN_STATS['parse_start_ts'] = start_ts
    print('{green}[*] [{}] Parsing new links from output/sources/{}...{reset}'.format(
        start_ts.strftime('%Y-%m-%d %H:%M:%S'),
        source_file.rsplit('/', 1)[-1],
        **ANSI,
    ))

def log_parsing_finished(num_new_links, parser_name):
    print('    > Adding {} new links to index (parsed import as {})'.format(
        num_new_links,
        parser_name,
    ))


### Indexing Stage

def log_indexing_process_started():
    start_ts = datetime.now()
    _LAST_RUN_STATS['index_start_ts'] = start_ts
    print('{green}[*] [{}] Saving main index files...{reset}'.format(
        start_ts.strftime('%Y-%m-%d %H:%M:%S'),
        **ANSI,
    ))

def log_indexing_started(out_dir, out_file):
    sys.stdout.write('    > {}/{}'.format(pretty_path(out_dir), out_file))

def log_indexing_finished(out_dir, out_file):
    end_ts = datetime.now()
    _LAST_RUN_STATS['index_end_ts'] = end_ts
    print('\r    √ {}/{}'.format(pretty_path(out_dir), out_file))


### Archiving Stage

def log_archiving_started(num_links, resume):
    start_ts = datetime.now()
    _LAST_RUN_STATS['start_ts'] = start_ts
    if resume:
        print('{green}[▶] [{}] Resuming archive updating for {} pages starting from {}...{reset}'.format(
             start_ts.strftime('%Y-%m-%d %H:%M:%S'),
             num_links,
             resume,
             **ANSI,
        ))
    else:
        print('{green}[▶] [{}] Updating content for {} pages in archive...{reset}'.format(
             start_ts.strftime('%Y-%m-%d %H:%M:%S'),
             num_links,
             **ANSI,
        ))

def log_archiving_paused(num_links, idx, timestamp):
    end_ts = datetime.now()
    _LAST_RUN_STATS['end_ts'] = end_ts
    print()
    print('\n{lightyellow}[X] [{now}] Downloading paused on link {timestamp} ({idx}/{total}){reset}'.format(
        **ANSI,
        now=end_ts.strftime('%Y-%m-%d %H:%M:%S'),
        idx=idx+1,
        timestamp=timestamp,
        total=num_links,
    ))
    print('    To view your archive, open: {}/index.html'.format(OUTPUT_DIR.replace(REPO_DIR + '/', '')))
    print('    Continue where you left off by running:')
    print('        {} {}'.format(
        pretty_path(sys.argv[0]),
        timestamp,
    ))

def log_archiving_finished(num_links):
    end_ts = datetime.now()
    _LAST_RUN_STATS['end_ts'] = end_ts
    seconds = end_ts.timestamp() - _LAST_RUN_STATS['start_ts'].timestamp()
    if seconds > 60:
        duration = '{0:.2f} min'.format(seconds / 60, 2)
    else:
        duration = '{0:.2f} sec'.format(seconds, 2)

    print('{}[√] [{}] Update of {} pages complete ({}){}'.format(
        ANSI['green'],
        end_ts.strftime('%Y-%m-%d %H:%M:%S'),
        num_links,
        duration,
        ANSI['reset'],
    ))
    print('    - {} links skipped'.format(_LAST_RUN_STATS['skipped']))
    print('    - {} links updated'.format(_LAST_RUN_STATS['succeeded']))
    print('    - {} links had errors'.format(_LAST_RUN_STATS['failed']))
    print('    To view your archive, open: {}/index.html'.format(OUTPUT_DIR.replace(REPO_DIR + '/', '')))


def log_link_archiving_started(link_dir, link, is_new):
    # [*] [2019-03-22 13:46:45] "Log Structured Merge Trees - ben stopford"
    #     http://www.benstopford.com/2015/02/14/log-structured-merge-trees/
    #     > output/archive/1478739709

    print('\n[{symbol_color}{symbol}{reset}] [{symbol_color}{now}{reset}] "{title}"'.format(
        symbol_color=ANSI['green' if is_new else 'black'],
        symbol='+' if is_new else '*',
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        title=link['title'] or link['url'],
        **ANSI,
    ))
    print('    {blue}{url}{reset}'.format(url=link['url'], **ANSI))
    print('    {} {}'.format(
        '>' if is_new else '√',
        pretty_path(link_dir),
    ))

def log_link_archiving_finished(link_dir, link, is_new, stats):
    total = sum(stats.values())

    if stats['failed'] > 0 :
        _LAST_RUN_STATS['failed'] += 1
    elif stats['skipped'] == total:
        _LAST_RUN_STATS['skipped'] += 1
    else:
        _LAST_RUN_STATS['succeeded'] += 1


def log_archive_method_started(method):
    print('      > {}'.format(method))

def log_archive_method_finished(result):
    """quote the argument with whitespace in a command so the user can 
       copy-paste the outputted string directly to run the cmd
    """
    required_keys = ('cmd', 'pwd', 'output', 'status', 'start_ts', 'end_ts')
    assert (
        isinstance(result, dict)
        and all(key in result for key in required_keys)
        and ('output' in result)
    ), 'Archive method did not return a valid result.'

    # Prettify CMD string and make it safe to copy-paste by quoting arguments
    quoted_cmd = ' '.join(
        '"{}"'.format(arg) if ' ' in arg else arg
        for arg in result['cmd']
    )

    if result['status'] == 'failed':
        # Prettify error output hints string and limit to five lines
        hints = getattr(result['output'], 'hints', None) or ()
        if hints:
            hints = hints if isinstance(hints, (list, tuple)) else hints.split('\n')
            hints = (
                '    {}{}{}'.format(ANSI['lightyellow'], line.strip(), ANSI['reset'])
                for line in hints[:5] if line.strip()
            )

        # Collect and prefix output lines with indentation
        output_lines = [
            '{}Failed:{} {}{}'.format(
                ANSI['red'],
                result['output'].__class__.__name__.replace('ArchiveError', ''), 
                result['output'],
                ANSI['reset']
            ),
            *hints,
            '{}Run to see full output:{}'.format(ANSI['lightred'], ANSI['reset']),
            '    cd {};'.format(result['pwd']),
            '    {}'.format(quoted_cmd),
        ]
        print('\n'.join(
            '        {}'.format(line)
            for line in output_lines
            if line
        ))
