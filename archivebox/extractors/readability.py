__package__ = 'archivebox.extractors'

from pathlib import Path
from tempfile import NamedTemporaryFile

from typing import Optional
import json

from ..index.schema import Link, ArchiveResult, ArchiveError
from ..system import run, atomic_write
from ..util import (
    enforce_types,
    is_static_file,
)
from ..config import (
    TIMEOUT,
    CURL_BINARY,
    SAVE_READABILITY,
    DEPENDENCIES,
    READABILITY_VERSION,
)
from ..logging_util import TimedProgress
from .title import get_html


@enforce_types
def should_save_readability(link: Link, out_dir: Optional[str]=None, overwrite: Optional[bool]=False) -> bool:
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    if not overwrite and (out_dir / 'readability').exists():
        return False

    return SAVE_READABILITY


@enforce_types
def save_readability(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download reader friendly version using @mozilla/readability"""

    out_dir = Path(out_dir or link.link_dir)
    output_folder = out_dir.absolute() / "readability"
    output = "readability"

    # Readability Docs: https://github.com/mozilla/readability

    status = 'succeeded'
    # fake command to show the user so they have something to try debugging if get_html fails
    cmd = [
        CURL_BINARY,
        link.url
    ]
    readability_content = None
    timer = TimedProgress(timeout, prefix='      ')
    try:
        document = get_html(link, out_dir)
        temp_doc = NamedTemporaryFile(delete=False)
        temp_doc.write(document.encode("utf-8"))
        temp_doc.close()

        if not document or len(document) < 10:
            raise ArchiveError('Readability could not find HTML to parse for article text')

        cmd = [
            DEPENDENCIES['READABILITY_BINARY']['path'],
            temp_doc.name,
            link.url,
        ]

        result = run(cmd, cwd=out_dir, timeout=timeout)
        try:
            result_json = json.loads(result.stdout)
            assert result_json and 'content' in result_json, 'Readability output is not valid JSON'
        except json.JSONDecodeError:
            raise ArchiveError('Readability was not able to archive the page', result.stdout + result.stderr)

        output_folder.mkdir(exist_ok=True)
        readability_content = result_json.pop("textContent") 
        atomic_write(str(output_folder / "content.html"), result_json.pop("content"))
        atomic_write(str(output_folder / "content.txt"), readability_content)
        atomic_write(str(output_folder / "article.json"), result_json)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 5)[-5:]
            if line.strip()
        ]
        hints = (
            'Got readability response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0):
            raise ArchiveError('Readability was not able to archive the page', hints)
    except (Exception, OSError) as err:
        status = 'failed'
        output = err
        cmd = [cmd[0], './{singlefile,dom}.html']
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=READABILITY_VERSION,
        output=output,
        status=status,
        index_texts=[readability_content] if readability_content else [],
        **timer.stats,  
    )
