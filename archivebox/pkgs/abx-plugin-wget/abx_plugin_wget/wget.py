__package__ = 'abx_plugin_wget'

import re
import os
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone

from archivebox.index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from archivebox.misc.logging_util import TimedProgress
from archivebox.misc.system import run, chmod_file
from archivebox.misc.util import (
    enforce_types,
    without_fragment,
    without_query,
    path,
    domain,
    urldecode,
    dedupe,
)

from .config import WGET_CONFIG
from .binaries import WGET_BINARY



def get_output_path():
    # TODO: actually save output into this folder, instead of do {domain}/**/index.html
    return 'wget/'

def get_embed_path(archiveresult=None):
    if not archiveresult:
        return get_output_path()

    link = archiveresult.snapshot.as_link()
    return wget_output_path(link)


@enforce_types
def should_save_wget(link: Link, out_dir: Optional[Path]=None, overwrite: Optional[bool]=False) -> bool:
    output_path = wget_output_path(link)
    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and output_path and (out_dir / output_path).exists():
        return False

    return WGET_CONFIG.SAVE_WGET


@enforce_types
def save_wget(link: Link, out_dir: Optional[Path]=None, timeout: int=WGET_CONFIG.WGET_TIMEOUT) -> ArchiveResult:
    """download full site using wget"""

    out_dir = Path(out_dir or link.link_dir)
    assert out_dir.exists()
    
    if WGET_CONFIG.SAVE_WARC:
        warc_dir = out_dir / "warc"
        warc_dir.mkdir(exist_ok=True)
        warc_path = warc_dir / str(int(datetime.now(timezone.utc).timestamp()))

    wget_binary = WGET_BINARY.load()
    assert wget_binary.abspath and wget_binary.version

    # WGET CLI Docs: https://www.gnu.org/software/wget/manual/wget.html
    output: ArchiveOutput = None
    # later options take precedence
    options = [
        *WGET_CONFIG.WGET_ARGS,
        *WGET_CONFIG.WGET_EXTRA_ARGS,
        '--timeout={}'.format(timeout),
        *(['--restrict-file-names={}'.format(WGET_CONFIG.WGET_RESTRICT_FILE_NAMES)] if WGET_CONFIG.WGET_RESTRICT_FILE_NAMES else []),
        *(['--warc-file={}'.format(str(warc_path))] if WGET_CONFIG.SAVE_WARC else []),
        *(['--page-requisites'] if WGET_CONFIG.SAVE_WGET_REQUISITES else []),
        *(['--user-agent={}'.format(WGET_CONFIG.WGET_USER_AGENT)] if WGET_CONFIG.WGET_USER_AGENT else []),
        *(['--load-cookies', str(WGET_CONFIG.WGET_COOKIES_FILE)] if WGET_CONFIG.WGET_COOKIES_FILE else []),
        *(['--compression=auto'] if WGET_CONFIG.WGET_AUTO_COMPRESSION else []),
        *([] if WGET_CONFIG.SAVE_WARC else ['--timestamping']),
        *([] if WGET_CONFIG.WGET_CHECK_SSL_VALIDITY else ['--no-check-certificate', '--no-hsts']),
        # '--server-response',  # print headers for better error parsing
    ]
    cmd = [
        str(wget_binary.abspath),
        *dedupe(options),
        link.url,
    ]

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        result = run(cmd, cwd=str(out_dir), timeout=timeout)
        output = wget_output_path(link)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 3)[-3:]
            if line.strip()
        ]
        files_downloaded = (
            int(output_tail[-1].strip().split(' ', 2)[1] or 0)
            if 'Downloaded:' in output_tail[-1]
            else 0
        )
        hints = (
            'Got wget response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0 and files_downloaded < 1) or output is None:
            if b'403: Forbidden' in result.stderr:
                raise ArchiveError('403 Forbidden (try changing WGET_USER_AGENT)', hints)
            if b'404: Not Found' in result.stderr:
                raise ArchiveError('404 Not Found', hints)
            if b'ERROR 500: Internal Server Error' in result.stderr:
                raise ArchiveError('500 Internal Server Error', hints)
            raise ArchiveError('Wget failed or got an error from the server', hints)
        
        if (out_dir / output).exists():
            chmod_file(output, cwd=str(out_dir))
        else:
            print(f'          {out_dir}/{output}')
            raise ArchiveError('Failed to find wget output after running', hints)
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=str(wget_binary.version),
        output=output,
        status=status,
        **timer.stats,
    )


@enforce_types
def unsafe_wget_output_path(link: Link) -> Optional[str]:
    # There used to be a bunch of complex reverse-engineering path mapping logic here,
    # but it was removed in favor of just walking through the output folder recursively to try to find the
    # html file that wget produced. It's *much much much* slower than deriving it statically, and is currently
    # one of the main bottlenecks of ArchiveBox's performance (the output data is often on a slow HDD or network mount).
    # But it's STILL better than trying to figure out URL -> html filepath mappings ourselves from first principles.
    full_path = without_fragment(without_query(path(link.url))).strip('/')
    search_dir = Path(link.link_dir) / domain(link.url).replace(":", "+") / urldecode(full_path)
    for _ in range(4):
        try:
            if os.access(search_dir, os.R_OK) and search_dir.is_dir():
                html_files = [
                    f for f in search_dir.iterdir()
                    if re.search(".+\\.[Ss]?[Hh][Tt][Mm][Ll]?$", str(f), re.I | re.M)
                ]
                if html_files:
                    return str(html_files[0].relative_to(link.link_dir))

                # sometimes wget'd URLs have no ext and return non-html
                # e.g. /some/example/rss/all -> some RSS XML content)
                #      /some/other/url.o4g   -> some binary unrecognized ext)
                # test this with archivebox add --depth=1 https://getpocket.com/users/nikisweeting/feed/all
                last_part_of_url = urldecode(full_path.rsplit('/', 1)[-1])
                for file_present in search_dir.iterdir():
                    if file_present == last_part_of_url:
                        return str((search_dir / file_present).relative_to(link.link_dir))
        except OSError:
            # OSError 36 and others can happen here, caused by trying to check for impossible paths
            # (paths derived from URLs can often contain illegal unicode characters or be too long,
            # causing the OS / filesystem to reject trying to open them with a system-level error)
            pass

        # Move up one directory level
        search_dir = search_dir.parent

        if str(search_dir) == link.link_dir:
            break

    # check for literally any file present that isnt an empty folder
    domain_dir = Path(domain(link.url).replace(":", "+"))
    files_within = [path for path in (Path(link.link_dir) / domain_dir).glob('**/*.*') if not str(path).endswith('.orig')]
    if files_within:
        return str((domain_dir / files_within[-1]).relative_to(link.link_dir))

    # abandon all hope, wget either never downloaded, or it produced an output path so horribly mutilated
    # that it's better we just pretend it doesnt exist
    # this is why ArchiveBox's specializes in REDUNDANTLY saving copies of sites with multiple different tools
    return None


@enforce_types
def wget_output_path(link: Link, nocache: bool=False) -> Optional[str]:
    """calculate the path to the wgetted .html file, since wget may
    adjust some paths to be different than the base_url path.

    See docs on: wget --adjust-extension (-E), --restrict-file-names=windows|unix|ascii, --convert-links

    WARNING: this function is extremely error prone because mapping URLs to filesystem paths deterministically
    is basically impossible. Every OS and filesystem have different requirements on what special characters are
    allowed, and URLs are *full* of all kinds of special characters, illegal unicode, and generally unsafe strings
    that you dont want anywhere near your filesystem. Also URLs can be obscenely long, but most filesystems dont
    accept paths longer than 250 characters. On top of all that, this function only exists to try to reverse engineer
    wget's approach to solving this problem, so this is a shittier, less tested version of their already insanely
    complicated attempt to do this. Here be dragons:
        - https://github.com/ArchiveBox/ArchiveBox/issues/549
        - https://github.com/ArchiveBox/ArchiveBox/issues/1373
        - https://stackoverflow.com/questions/9532499/check-whether-a-path-is-valid-in-python-without-creating-a-file-at-the-paths-ta
        - and probably many more that I didn't realize were caused by this...

    The only constructive thing we could possibly do to this function is to figure out how to remove it.

    Preach loudly to anyone who will listen: never attempt to map URLs to filesystem paths,
    and pray you never have to deal with the aftermath of someone else's attempt to do so...
    """
    
    # Wget downloads can save in a number of different ways depending on the url:
    #    https://example.com
    #       > example.com/index.html
    #    https://example.com?v=zzVa_tX1OiI
    #       > example.com/index.html@v=zzVa_tX1OiI.html
    #    https://www.example.com/?v=zzVa_tX1OiI
    #       > example.com/index.html@v=zzVa_tX1OiI.html

    #    https://example.com/abc
    #       > example.com/abc.html
    #    https://example.com/abc/
    #       > example.com/abc/index.html
    #    https://example.com/abc?v=zzVa_tX1OiI.html
    #       > example.com/abc@v=zzVa_tX1OiI.html
    #    https://example.com/abc/?v=zzVa_tX1OiI.html
    #       > example.com/abc/index.html@v=zzVa_tX1OiI.html

    #    https://example.com/abc/test.html
    #       > example.com/abc/test.html
    #    https://example.com/abc/test?v=zzVa_tX1OiI
    #       > example.com/abc/test@v=zzVa_tX1OiI.html
    #    https://example.com/abc/test/?v=zzVa_tX1OiI
    #       > example.com/abc/test/index.html@v=zzVa_tX1OiI.html

    cache_key = f'{link.url_hash}:{link.timestamp}-{link.downloaded_at and link.downloaded_at.timestamp()}-wget-output-path'
    
    if not nocache:
        from django.core.cache import cache
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result


    # There's also lots of complexity around how the urlencoding and renaming
    # is done for pages with query and hash fragments, extensions like shtml / htm / php / etc,
    # unicode escape sequences, punycode domain names, unicode double-width characters, extensions longer than
    # 4 characters, paths with multipe extensions, etc. the list goes on...

    output_path = None
    try:
        output_path = unsafe_wget_output_path(link)
    except Exception as err:
        pass           # better to pretend it just failed to download than expose gnarly OSErrors to users

    # check for unprintable unicode characters
    # https://github.com/ArchiveBox/ArchiveBox/issues/1373
    if output_path:
        safe_path = output_path.encode('utf-8', 'replace').decode()
        if output_path != safe_path:
            # contains unprintable unicode characters that will break other parts of archivebox
            # better to pretend it doesnt exist and fallback to parent dir than crash archivebox
            output_path = None

    # check for a path that is just too long to safely handle across different OS's
    # https://github.com/ArchiveBox/ArchiveBox/issues/549
    if output_path and len(output_path) > 250:
        output_path = None

    if output_path:
        if not nocache:
            cache.set(cache_key, output_path)
        return output_path

    # fallback to just the domain dir
    search_dir = Path(link.link_dir) / domain(link.url).replace(":", "+")
    if os.access(search_dir, os.R_OK) and search_dir.is_dir():
        return domain(link.url).replace(":", "+")

    # fallback to just the domain dir without port
    search_dir = Path(link.link_dir) / domain(link.url).split(":", 1)[0]
    if os.access(search_dir, os.R_OK) and search_dir.is_dir():
        return domain(link.url).split(":", 1)[0]

    return None
