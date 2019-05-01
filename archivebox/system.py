__package__ = 'archivebox'


import os
import shutil

import json as pyjson
from typing import Optional, Union, Set, Tuple

from crontab import CronTab

from subprocess import (
    Popen,
    PIPE,
    DEVNULL, 
    CompletedProcess,
    TimeoutExpired,
    CalledProcessError,
)

from .util import enforce_types, ExtendedEncoder
from .config import OUTPUT_PERMISSIONS


def run(*popenargs, input=None, capture_output=False, timeout=None, check=False, **kwargs):
    """Patched of subprocess.run to fix blocking io making timeout=innefective"""

    if input is not None:
        if 'stdin' in kwargs:
            raise ValueError('stdin and input arguments may not both be used.')
        kwargs['stdin'] = PIPE

    if capture_output:
        if ('stdout' in kwargs) or ('stderr' in kwargs):
            raise ValueError('stdout and stderr arguments may not be used '
                             'with capture_output.')
        kwargs['stdout'] = PIPE
        kwargs['stderr'] = PIPE

    with Popen(*popenargs, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except TimeoutExpired:
            process.kill()
            try:
                stdout, stderr = process.communicate(input, timeout=2)
            except:
                pass
            raise TimeoutExpired(popenargs[0][0], timeout)
        except BaseException:
            process.kill()
            # We don't call process.wait() as .__exit__ does that for us.
            raise 
        retcode = process.poll()
        if check and retcode:
            raise CalledProcessError(retcode, process.args,
                                     output=stdout, stderr=stderr)
    return CompletedProcess(process.args, retcode, stdout, stderr)


def atomic_write(contents: Union[dict, str, bytes], path: str) -> None:
    """Safe atomic write to filesystem by writing to temp file + atomic rename"""
    try:
        tmp_file = '{}.tmp'.format(path)
        
        if isinstance(contents, bytes):
            args = {'mode': 'wb+'}
        else:
            args = {'mode': 'w+', 'encoding': 'utf-8'}

        with open(tmp_file, **args) as f:
            if isinstance(contents, dict):
                pyjson.dump(contents, f, indent=4, sort_keys=True, cls=ExtendedEncoder)
            else:
                f.write(contents)
            
            os.fsync(f.fileno())

        os.rename(tmp_file, path)
        chmod_file(path)
    finally:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)


@enforce_types
def chmod_file(path: str, cwd: str='.', permissions: str=OUTPUT_PERMISSIONS, timeout: int=30) -> None:
    """chmod -R <permissions> <cwd>/<path>"""

    if not os.path.exists(os.path.join(cwd, path)):
        raise Exception('Failed to chmod: {} does not exist (did the previous step fail?)'.format(path))

    chmod_result = run(['chmod', '-R', permissions, path], cwd=cwd, stdout=DEVNULL, stderr=PIPE, timeout=timeout)
    if chmod_result.returncode == 1:
        print('     ', chmod_result.stderr.decode())
        raise Exception('Failed to chmod {}/{}'.format(cwd, path))


@enforce_types
def copy_and_overwrite(from_path: str, to_path: str):
    """copy a given file or directory to a given path, overwriting the destination"""
    if os.path.isdir(from_path):
        shutil.rmtree(to_path, ignore_errors=True)
        shutil.copytree(from_path, to_path)
    else:
        with open(from_path, 'rb') as src:
            atomic_write(src.read(), to_path)


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
