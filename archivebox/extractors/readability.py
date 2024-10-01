__package__ = 'archivebox.extractors'

from pathlib import Path
from tempfile import NamedTemporaryFile

from typing import Optional
import json

from ..index.schema import Link, ArchiveResult, ArchiveError
from archivebox.misc.system import run, atomic_write
from archivebox.misc.util import enforce_types, is_static_file
from ..logging_util import TimedProgress
from .title import get_html

def get_output_path():
    return 'readability/'

def get_embed_path(archiveresult=None):
    return get_output_path() + 'content.html'


@enforce_types
def should_save_readability(link: Link, out_dir: Optional[str]=None, overwrite: Optional[bool]=False) -> bool:
    from plugins_extractor.readability.apps import READABILITY_CONFIG
    
    if is_static_file(link.url):
        return False

    output_subdir = (Path(out_dir or link.link_dir) / get_output_path())
    if not overwrite and output_subdir.exists():
        return False

    return READABILITY_CONFIG.SAVE_READABILITY


@enforce_types
def save_readability(link: Link, out_dir: Optional[str]=None, timeout: int=0) -> ArchiveResult:
    """download reader friendly version using @mozilla/readability"""
    
    from plugins_extractor.readability.apps import READABILITY_CONFIG, READABILITY_BINARY
    
    READABILITY_BIN = READABILITY_BINARY.load()
    assert READABILITY_BIN.abspath and READABILITY_BIN.version

    timeout = timeout or READABILITY_CONFIG.READABILITY_TIMEOUT
    output_subdir = Path(out_dir or link.link_dir).absolute() / get_output_path()
    output = get_output_path()

    # Readability Docs: https://github.com/mozilla/readability

    status = 'succeeded'
    # fake command to show the user so they have something to try debugging if get_html fails
    cmd = [
        str(READABILITY_BIN.abspath),
        '{dom,singlefile}.html',
        link.url,
    ]
    readability_content = None
    timer = TimedProgress(timeout, prefix='      ')
    try:
        document = get_html(link, Path(out_dir or link.link_dir))
        temp_doc = NamedTemporaryFile(delete=False)
        temp_doc.write(document.encode("utf-8"))
        temp_doc.close()

        if not document or len(document) < 10:
            raise ArchiveError('Readability could not find HTML to parse for article text')

        cmd = [
            str(READABILITY_BIN.abspath),
            temp_doc.name,
            link.url,
        ]
        result = run(cmd, cwd=out_dir, timeout=timeout, text=True)
        try:
            result_json = json.loads(result.stdout)
            assert result_json and 'content' in result_json, 'Readability output is not valid JSON'
        except json.JSONDecodeError:
            raise ArchiveError('Readability was not able to archive the page (invalid JSON)', result.stdout + result.stderr)

        output_subdir.mkdir(exist_ok=True)
        readability_content = result_json.pop("textContent") 
        atomic_write(str(output_subdir / "content.html"), result_json.pop("content"))
        atomic_write(str(output_subdir / "content.txt"), readability_content)
        atomic_write(str(output_subdir / "article.json"), result_json)

        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).rsplit('\n', 5)[-5:]
            if line.strip()
        ]
        hints = (
            'Got readability response code: {}.'.format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        if (result.returncode > 0):
            raise ArchiveError(f'Readability was not able to archive the page (status={result.returncode})', hints)
    except (Exception, OSError) as err:
        status = 'failed'
        output = err

        # prefer Chrome dom output to singlefile because singlefile often contains huge url(data:image/...base64) strings that make the html too long to parse with readability
        cmd = [cmd[0], './{dom,singlefile}.html']
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=str(READABILITY_BIN.version),
        output=output,
        status=status,
        index_texts=[readability_content] if readability_content else [],
        **timer.stats,  
    )
