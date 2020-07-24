__package__ = 'archivebox'


import os
import shutil

from json import dump
from pathlib import Path
from typing import Optional, Union, Set, Tuple
from subprocess import run as subprocess_run

from crontab import CronTab
from atomicwrites import atomic_write as lib_atomic_write

from .util import enforce_types, ExtendedEncoder
from .config import OUTPUT_PERMISSIONS


def run(*args, input=None, capture_output=True, text=False, **kwargs):
    """Patched of subprocess.run to fix blocking io making timeout=innefective"""

    if input is not None:
        if 'stdin' in kwargs:
            raise ValueError('stdin and input arguments may not both be used.')

    if capture_output:
        if ('stdout' in kwargs) or ('stderr' in kwargs):
            raise ValueError('stdout and stderr arguments may not be used '
                             'with capture_output.')

    return subprocess_run(*args, input=input, capture_output=capture_output, text=text, **kwargs)


@enforce_types
def atomic_write(path: Union[Path, str], contents: Union[dict, str, bytes], overwrite: bool=True) -> None:
    """Safe atomic write to filesystem by writing to temp file + atomic rename"""

    mode = 'wb+' if isinstance(contents, bytes) else 'w'

    # print('\n> Atomic Write:', mode, path, len(contents), f'overwrite={overwrite}')
    with lib_atomic_write(path, mode=mode, overwrite=overwrite) as f:
        if isinstance(contents, dict):
            dump(contents, f, indent=4, sort_keys=True, cls=ExtendedEncoder)
        elif isinstance(contents, (bytes, str)):
            f.write(contents)
    os.chmod(path, int(OUTPUT_PERMISSIONS, base=8))

@enforce_types
def chmod_file(path: str, cwd: str='.', permissions: str=OUTPUT_PERMISSIONS) -> None:
    """chmod -R <permissions> <cwd>/<path>"""

    root = Path(cwd) / path
    if not root.exists():
        raise Exception('Failed to chmod: {} does not exist (did the previous step fail?)'.format(path))

    if not root.is_dir():
        os.chmod(root, int(OUTPUT_PERMISSIONS, base=8))
    else:
        for subpath in Path(path).glob('**/*'):
            os.chmod(subpath, int(OUTPUT_PERMISSIONS, base=8))


@enforce_types
def copy_and_overwrite(from_path: str, to_path: str):
    """copy a given file or directory to a given path, overwriting the destination"""
    if os.path.isdir(from_path):
        shutil.rmtree(to_path, ignore_errors=True)
        shutil.copytree(from_path, to_path)
    else:
        with open(from_path, 'rb') as src:
            contents = src.read()
        atomic_write(to_path, contents)


@enforce_types
def get_dir_size(path: str, recursive: bool=True, pattern: Optional[str]=None) -> Tuple[int, int, int]:
    """get the total disk size of a given directory, optionally summing up 
       recursively and limiting to a given filter list
    """
    num_bytes, num_dirs, num_files = 0, 0, 0
    for entry in os.scandir(path):
        if (pattern is not None) and (pattern not in entry.path):
            continue
        if entry.is_dir(follow_symlinks=False):
            if not recursive:
                continue
            num_dirs += 1
            bytes_inside, dirs_inside, files_inside = get_dir_size(entry.path)
            num_bytes += bytes_inside
            num_dirs += dirs_inside
            num_files += files_inside
        else:
            num_bytes += entry.stat(follow_symlinks=False).st_size
            num_files += 1
    return num_bytes, num_dirs, num_files


CRON_COMMENT = 'archivebox_schedule'


@enforce_types
def dedupe_cron_jobs(cron: CronTab) -> CronTab:
    deduped: Set[Tuple[str, str]] = set()

    for job in list(cron):
        unique_tuple = (str(job.slices), job.command)
        if unique_tuple not in deduped:
            deduped.add(unique_tuple)
        cron.remove(job)

    for schedule, command in deduped:
        job = cron.new(command=command, comment=CRON_COMMENT)
        job.setall(schedule)
        job.enable()

    return cron
