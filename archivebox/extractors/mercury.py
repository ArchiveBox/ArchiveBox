__package__ = 'archivebox.extractors'

from pathlib import Path

from typing import Optional
import json

from .readability import get_html
from ..index.schema import Link, ArchiveResult, ArchiveError
from ..system import run, atomic_write
from ..util import (
    enforce_types,
    is_static_file,

)
from ..config import (
    TIMEOUT,
    SAVE_MERCURY,
    DEPENDENCIES,
    MERCURY_VERSION,
)
from ..logging_util import TimedProgress

@enforce_types
def should_save_mercury(link: Link, out_dir: Optional[str]=None) -> bool:
    out_dir = out_dir or link.link_dir
    if is_static_file(link.url):
        return False

    output = Path(out_dir or link.link_dir) / 'mercury'
    return SAVE_MERCURY and MERCURY_VERSION and (not output.exists())


@enforce_types
def save_mercury(link: Link, out_dir: Optional[str]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """download reader friendly version using @postlight/mercury-parser"""

    out_dir = Path(out_dir or link.link_dir)
    output_folder = out_dir.absolute() / "mercury"
    output = str(output_folder)

    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        document = get_html(link, out_dir)
        temp_doc = NamedTemporaryFile(delete=False)
        temp_doc.write(document.encode("utf-8"))
        temp_doc.close()

        cmd = [
            DEPENDENCIES['MERCURY_BINARY']['path'],
            temp_doc.name,
            link.url,
        ]
        result = run(cmd, cwd=out_dir, timeout=timeout)
        result_json = json.loads(result.stdout)

        output_folder.mkdir(exist_ok=True)
        atomic_write(str(output_folder / "content.html"), result_json.pop("content"))
        atomic_write(str(output_folder / "content.txt"), result_json.pop("content_txt"))
        atomic_write(str(output_folder / "article.json"), result_json)

        # parse out number of files downloaded from last line of stderr:
        #  "Downloaded: 76 files, 4.0M in 1.6s (2.52 MB/s)"
        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit('\n', 20)[-20:]
            if line.strip()
        ]
        hints = (
            'Got mercury response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0):
            raise ArchiveError('Mercury parser was not able to archive the page', hints)
    except (Exception, OSError) as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=MERCURY_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
