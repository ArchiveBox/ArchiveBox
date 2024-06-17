__package__ = "archivebox.extractors"

from pathlib import Path

from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveError
from ..system import run, chmod_file, get_dir_size
from ..util import enforce_types, is_static_file, dedupe, URL_REGEX
from ..config import (
    TIMEOUT,
    SAVE_PAPERS,
    DEPENDENCIES,
    PAPERSDL_VERSION,
    PAPERSDL_ARGS,
    PAPERSDL_EXTRA_ARGS,
)
from ..logging_util import TimedProgress
from .title import get_html

def get_output_path():
    return 'papers_dl/'

@enforce_types
def should_save_papers(
    link: Link, out_dir: Optional[Path] = None, overwrite: Optional[bool] = False
) -> bool:
    if is_static_file(link.url):
        return False

    out_dir = out_dir or Path(link.link_dir)
    # Since most links that ArchiveBox sees aren't papers, we try to avoid
    # unnecessary searches by skipping things that look like a URL.
    # But some URLs are accessible with SciHub and we don't want to miss those.
    # Those URLs usually have other unique identifiers in the HTML, so we
    # can look for those to see if it's a URL worth trying to fetch

    # if identifier looks like a url, then try to look at the html
    # and see if we can find a more reliable identifier inside
    cmd = [
        DEPENDENCIES["PAPERSDL_BINARY"]["path"],
        "parse",
    ]

    if URL_REGEX.match(link.url):
        document = get_html(link, out_dir)

        result = run(cmd, input=document.encode("utf-8"))
        output = result.stdout.strip()
    else:
        # check if it looks like a valid id
        result = run(cmd, input=link.url.encode("utf-8"))
        output = result.stdout.strip()

    # we didn't get a valid result, so we shouldn't search for it
    if len(output) == 0:
        return False

    if not overwrite and (out_dir / "papers_dl").exists():
        return False

    return SAVE_PAPERS


@enforce_types
def save_papers(
    link: Link, out_dir: Optional[Path] = None, timeout: int = TIMEOUT
) -> ArchiveResult:
    """download a paper with an identifier using papers-dl"""

    out_dir = Path(out_dir or link.link_dir)
    output = "papers_dl"
    output_folder = out_dir.absolute() / output

    # later options take precedence
    options = [
        *PAPERSDL_ARGS,
        *PAPERSDL_EXTRA_ARGS,
    ]
    cmd = [
        DEPENDENCIES["PAPERSDL_BINARY"]["path"],
        "-v",
        "fetch",
        "-o",
        str(output_folder),
        *dedupe(options),
        link.url,
    ]

    status = "succeeded"
    timer = TimedProgress(timeout, prefix="      ")
    result = None
    try:
        output_folder.mkdir(exist_ok=True)
        result = run(cmd, cwd=str(output_folder), timeout=timeout)
        chmod_file(output, cwd=str(out_dir))

        output_tail = [
            line.strip()
            for line in (result.stdout + result.stderr).decode().rsplit("\n", 5)[-5:]
            if line.strip()
        ]
        hints = (
            "Got papers-dl response code: {}.".format(result.returncode),
            *output_tail,
        )

        # Check for common failure cases
        _, _, num_files = get_dir_size(out_dir / output)
        if (result.returncode > 0) or num_files == 0:
            raise ArchiveError(
                f"papers-dl was not able to archive the page (status={result.returncode})",
                hints,
            )
    except (Exception, OSError) as err:
        status = "failed"
        # TODO: Make this prettier. This is necessary to run the command (escape JSON internal quotes).
        # cmd[2] = browser_args.replace('"', "\\\"")
        if result:
            err.hints = (result.stdout + result.stderr).decode().split("\n")
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=PAPERSDL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
