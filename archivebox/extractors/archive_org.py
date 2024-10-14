__package__ = 'archivebox.extractors'


from pathlib import Path
from typing import Optional, List, Dict, Tuple
from collections import defaultdict

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from archivebox.misc.system import run, chmod_file
from archivebox.misc.util import enforce_types, is_static_file, dedupe
from archivebox.plugins_extractor.archivedotorg.apps import ARCHIVEDOTORG_CONFIG
from archivebox.plugins_extractor.curl.apps import CURL_CONFIG, CURL_BINARY

from ..logging_util import TimedProgress


def get_output_path():
    return 'archive.org.txt'


@enforce_types
def should_save_archive_dot_org(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / get_output_path()).exists():
        # if open(path, 'r', encoding='utf-8').read().strip() != 'None':
        return False

    return ARCHIVEDOTORG_CONFIG.SAVE_ARCHIVE_DOT_ORG

@enforce_types
def save_archive_dot_org(link: Link, out_dir: Optional[Path]=None, timeout: int=CURL_CONFIG.CURL_TIMEOUT) -> ArchiveResult:
    """submit site to archive.org for archiving via their service, save returned archive url"""

    curl_binary = CURL_BINARY.load()
    assert curl_binary.abspath and curl_binary.version

    out_dir = out_dir or Path(link.link_dir)
    output: ArchiveOutput = get_output_path()
    archive_org_url = None
    submit_url = 'https://web.archive.org/save/{}'.format(link.url)
    # later options take precedence
    options = [
        *CURL_CONFIG.CURL_ARGS,
        *CURL_CONFIG.CURL_EXTRA_ARGS,
        '--head',
        '--max-time', str(timeout),
        *(['--user-agent', '{}'.format(CURL_CONFIG.CURL_USER_AGENT)] if CURL_CONFIG.CURL_USER_AGENT else []),
        *([] if CURL_CONFIG.CURL_CHECK_SSL_VALIDITY else ['--insecure']),
    ]
    cmd = [
        str(curl_binary.abspath),
        *dedupe(options),
        submit_url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout, text=True)
        content_location, errors = parse_archive_dot_org_response(result.stdout)
        if content_location:
            archive_org_url = content_location[0]
        elif len(errors) == 1 and 'RobotAccessControlException' in errors[0]:
            archive_org_url = None
            # raise ArchiveError('Archive.org denied by {}/robots.txt'.format(domain(link.url)))
        elif errors:
            raise ArchiveError(', '.join(errors))
        else:
            raise ArchiveError('Failed to find "content-location" URL header in Archive.org response.')
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    if output and not isinstance(output, Exception):
        # instead of writing None when archive.org rejects the url write the
        # url to resubmit it to archive.org. This is so when the user visits
        # the URL in person, it will attempt to re-archive it, and it'll show the
        # nicer error message explaining why the url was rejected if it fails.
        archive_org_url = archive_org_url or submit_url
        with open(str(out_dir / output), 'w', encoding='utf-8') as f:
            f.write(archive_org_url)
        chmod_file(str(out_dir / output), cwd=str(out_dir))
        output = archive_org_url

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=str(curl_binary.version),
        output=output,
        status=status,
        **timer.stats,
    )

@enforce_types
def parse_archive_dot_org_response(response: str) -> Tuple[List[str], List[str]]:
    # Parse archive.org response headers
    headers: Dict[str, List[str]] = defaultdict(list)

    # lowercase all the header names and store in dict
    for header in response.splitlines():
        if ':' not in header or not header.strip():
            continue
        name, val = header.split(':', 1)
        headers[name.lower().strip()].append(val.strip())

    # Get successful archive url in "content-location" header or any errors
    content_location = headers.get('content-location', headers['location'])
    errors = headers['x-archive-wayback-runtime-error']
    return content_location, errors

