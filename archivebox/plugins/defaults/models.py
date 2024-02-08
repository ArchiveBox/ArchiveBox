__package__ = 'archivebox.plugins.defaults'

# import shutil

import re

from typing import List, Dict, Any
from pathlib import Path

from django.db import models, transaction
from django.utils.functional import cached_property

from solo.models import SingletonModel                        # type: ignore[import-untyped]


from config import bin_path, bin_version

ConfigDict = Dict[str, Any]


# def bin_path(binary: str) -> str | None:
#     return shutil.which(str(Path(binary).expanduser())) or shutil.which(str(binary)) or binary

# def bin_version(bin_path: str, cmd: str | None=None) -> str | None:
#     return '0.0.0'

# def pretty_path(path: Path) -> str:
#     """take a Path object and return the path as a string relative to the current directory"""

#     if not path:
#         return ''

#     return str(path.expanduser().resolve().relative_to(Path.cwd().resolve()))


class ArchiveBoxBaseDependency(models.Model):
    singleton_instance_id = 1

    id = models.AutoField(default=singleton_instance_id, primary_key=True)

    NAME = 'DEFAULT'
    LABEL = "Default"
    REQUIRED = False

    PARENT_DEPENDENCIES: List[str] = []

    BIN_DEPENDENCIES: List[str] = []
    APT_DEPENDENCIES: List[str] = []
    BREW_DEPENDENCIES: List[str] = []
    PIP_DEPENDENCIES: List[str] = []
    NPM_DEPENDENCIES: List[str] = []

    DEFAULT_BINARY: str | None              = '/bin/bash'
    DEFAULT_START_CMD: str | None           = '/bin/bash -c "while true; do sleep 1; done"'
    DEFAULT_PID_FILE: str | None            = 'logs/{NAME}_WORKER.pid'
    DEFAULT_STOP_CMD: str | None            = 'kill "$(<{PID_FILE})"'
    DEFAULT_VERSION_COMMAND: str | None     = '{BINARY} --version'
    DEFAULT_ARGS: str | None                = ''

    VERSION_CMD = '{BINARY} --version'

    ENABLED = models.BooleanField(default=True, editable=False)
    BINARY = models.CharField(max_length=255, default=DEFAULT_BINARY)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS)
    
    # START_CMD = models.CharField(max_length=255, default=DEFAULT_START_CMD)
    # WORKERS = models.IntegerField(default=1)

    class Meta:
        abstract = True
        app_label = 'defaults'

    def __str__(self):
        return f"{self.LABEL} Dependency Configuration"

    def __json__(self):
        return {
            'type': 'ArchiveBoxDependency',
            '__class__': self.__class__.__name__,
            'NAME': self.NAME,
            'LABEL': self.LABEL,
            'ENABLED': self.ENABLED,
            'BINARY': self.BINARY,
            'ARGS': self.ARGS,
            # 'START_CMD': self.START_CMD,
            # 'WORKERS': self.WORKERS,
        }

    @cached_property
    def bin_path(self) -> str:
        return bin_path(self.BINARY or self.DEFAULT_BINARY)

    @cached_property
    def bin_version(self) -> str | None:
        print(f'ArchiveBoxBaseDependency.bin_version({self.bin_path}, cmd={self.VERSION_CMD.format(BINARY=self.BINARY)})')
        return bin_version(self.bin_path, cmd=self.VERSION_CMD.format(BINARY=self.BINARY))
        # return bin_version(self.bin_path, cmd=self.VERSION_CMD)

    @cached_property
    def is_valid(self) -> bool:
        return bool(self.bin_path and self.bin_version)

    @cached_property
    def is_enabled(self) -> bool:
        return bool(self.ENABLED and self.is_valid)

    @cached_property
    def pretty_version(self) -> str:
        if self.is_enabled:
            if self.is_valid:
                color, symbol, note, version = 'green', '√', 'valid', ''

                parsed_version_num = re.search(r'[\d\.]+', self.bin_version)
                if parsed_version_num:
                    version = f'v{parsed_version_num[0]}'

            if not self.bin_version:
                color, symbol, note, version = 'red', 'X', 'invalid', '?'
        else:
            color, symbol, note, version = 'lightyellow', '-', 'disabled', '-'

        path = pretty_path(self.bin_path)

        return ' '.join((
            ANSI[color],
            symbol,
            ANSI['reset'],
            name.ljust(21),
            version.ljust(14),
            ANSI[color],
            note.ljust(8),
            ANSI['reset'],
            path.ljust(76),
        ))

    # @helper
    def install_parents(self, config):
        return {
            # parent_dependency.NAME: parent_dependency.get_solo().install_self()
            parent_dependency: parent_dependency
            for parent_dependency in self.PARENT_DEPENDENCIES
        }

    # @helper
    def install_self(self, config):
        assert all(self.install_parents(config=config).values())

        BashEnvironmentDependency.get_solo().install_pkgs(self.BIN_DEPENDENCIES)
        AptEnvironmentDependency.get_solo().install_pkgs(self.APT_DEPENDENCIES)
        BrewEnvironmentDependency.get_solo().install_pkgs(self.BREW_DEPENDENCIES)
        PipEnvironmentDependency.get_solo().install_pkgs(self.PIP_DEPENDENCIES)
        NPMEnvironmentDependency.get_solo().install_pkgs(self.NPM_DEPENDENCIES)

        assert self.is_valid
        return self.bin_version

    # @task
    def run(args, pwd, timeout):
        errors = None
        timer = TimedProgress(timeout, prefix='      ')
        try:
            proc = run(cmd=[self.bin_path, *args], pwd=pwd, timeout=timeout)

        except Exception as err:
            errors = err
        finally:
            timer.end()

        return proc, timer, errors

class ArchiveBoxDefaultDependency(ArchiveBoxBaseDependency, SingletonModel):
    singleton_instance_id = 1

    id = models.AutoField(default=singleton_instance_id, primary_key=True)

    ENABLED = models.BooleanField(default=True, editable=True)

    class Meta:                 # pyright: ignore [reportIncompatibleVariableOverride]
        abstract = False
        app_label = 'defaults'
        verbose_name = 'Default Configuration: Dependencies'


class ArchiveBoxBaseExtractor(models.Model):
    singleton_instance_id = 1

    id = models.AutoField(default=singleton_instance_id, primary_key=True)

    NAME = 'DEFAULT'
    LABEL = 'Default'

    DEFAULT_DEPENDENCY = ArchiveBoxDefaultDependency
    DEPENDENCY = DEFAULT_DEPENDENCY


    DEFAULT_ENABLED = True
    DEFAULT_CMD = ['{DEPENDENCY.BINARY}', '{ARGS}', '{url}']
    DEFAULT_ARGS = ['--timeout={TIMEOUT}']
    DEFAULT_TIMEOUT = '{TIMEOUT}'
    # DEFAULT_USER_AGENT = '{USER_AGENT}'
    # DEFAULT_COOKIES_TXT = '{COOKIES_TXT}'

    ENABLED = models.BooleanField(default=DEFAULT_ENABLED, editable=True)

    CMD = models.CharField(max_length=255, default=DEFAULT_CMD)
    ARGS = models.CharField(max_length=255, default=DEFAULT_ARGS)
    TIMEOUT = models.CharField(max_length=255, default=DEFAULT_TIMEOUT)
    
    ALIASES = {
        'ENABLED': (f'SAVE_{NAME}', f'USE_{NAME}', f'FETCH_{NAME}'),
    }

    def __str__(self):
        return f"{self.LABEL} Extractor Configuration"

    class Meta:             # pyright: ignore [reportIncompatibleVariableOverride]
        abstract = True
        verbose_name = "Default Extractor Configuration"
        app_label = 'defaults'

    @cached_property
    def dependency(self):
        return self.DEPENDENCY.get_solo()

    def __json__(self):
        return {
            'type': 'ArchiveBoxExtractor',
            '__class__': self.__class__.__name__,
            'NAME': self.NAME,
            'LABEL': self.LABEL,
            'ENABLED': self.ENABLED,
            'DEPENDENCY': self.dependency.__json__(),
            'ARGS': self.ARGS,
            'CMD': self.CMD,
            'TIMEOUT': self.TIMEOUT,
            'is_valid': self.is_valid,
            'is_enabled': self.is_enabled,
        }


    def format_args(self, csv: List[str], **config):
        un_prefixed_config = {**self.__json__()}          # e.g. ENABLED=True
        prefixed_config = {                               # e.g. GALLERYDL_ENABLED=True
            f'{self.NAME}_{key}': value
            for key, value in un_prefixed_config.items()
        }

        merged_config = {
            **config,                  # e.g. TIMEOUT=60
            **un_prefixed_config,      # e.g. ENABLED=True
            **prefixed_config,         # e.g. GALLERYDL_ENABLED=True
        }
        formatted_config = [
            arg.format(**merged_config)
            for arg in csv
        ]

        return formatted_config

    @cached_property
    def is_valid(self):
        if not self.dependency.is_valid:
            return False

        # TIMEOUT must be at least 5 seconds
        # if self.TIMEOUT < 5:
        #     return False

        # assert Path(self.COOKIES_TXT).exists()
        # TODO: validate user agent with uaparser
        # TODO: validate args, cookies.txt?
        return True

    @cached_property
    def is_enabled(self):
        return self.ENABLED and self.is_valid and self.dependency.is_enabled


    def save(self, *args, **kwargs):
        # assert self.is_valid

        with transaction.atomic():
            result = super().save(*args, **kwargs)
            # post to message bus:
            print({
                'type': f'{self.__class__.__name__}.save',
                'diff': self.__json__(),
                'kwargs': kwargs,
            })
            # potential consumers of this event:
            #    - event logger: write to events.log
            #    - config file updater: writes to ArchiveBox.conf
            #    - supervisor: restarts relevant dependencies/extractors
            #    - etc...

        return result

    def out_dir(self, url: str, snapshot_dir: Path, config: ConfigDict):
        return (snapshot_dir / self.NAME)

    def create_out_dir(self, url: str, snapshot_dir: Path, config: ConfigDict):
        out_dir = self.out_dir(url=url, snapshot_dir=snapshot_dir, config=config)
        return out_dir.mkdir(exist_ok=True)

    def should_extract(self, url: str, snapshot_dir: Path, config: ConfigDict):
        # return False if extractor is disabled
        if not self.is_enabled:
            return False

        out_dir = self.out_dir(url=url, snapshot_dir=snapshot_dir, config=config)
        
        if has_existing_output := out_dir.glob('*'):
            return False

        if not (has_write_access := os.access(out_dir, os.W_OK | os.X_OK)):
            return False

        return True


    def get_dependency_cmd(self, url: str, extractor_dir: Path, config: ConfigDict):
        return [
            self.format_args(self.CMD, **config),
            url,
            *self.format_args(self.ARGS, **config),   # TODO: split and requote this properly
        ]

    # @requires_config('HOSTNAME', 'TIMEOUT', 'USER_AGENT', 'CHECK_SSL_VALIDITY')
    def extract(self, url: str, snapshot_dir: Path, config: ConfigDict):
        if not self.ENABLED:
            return

        extractor_dir = self.create_extractor_directory(snapshot_dir)

        cmd = self.get_dependency_cmd(url=url, extractor_dir=extractor_dir, config=config)

        status, stdout, stderr, output_path = 'failed', '', '', None
        try:
            proc, timer, errors = self.dependency.run(cmd, cwd=extractor_dir, timeout=self.TIMEOUT)
            stdout, stderr = proc.stdout, proc.stderr
            
            if 'ERROR: Unsupported URL' in stderr:
                hints = ('gallery-dl doesnt support this type of url yet',)
                raise ArchiveError('Failed to save gallerydl', hints)

            if proc.returncode == 0 and 'finished' in stdout:
                output_path = extractor_dir / 'index.html'
                status = 'succeeded'
        except Exception as err:
            stderr += err

        num_bytes, num_dirs, num_files = get_dir_size(extractor_dir)

        return ArchiveResult(
            cmd=cmd,
            pwd=str(out_dir),
            cmd_version=self.dependency.bin_version,
            cmd_path=self.dependency.bin_path,
            cmd_hostname=config.HOSTNAME,

            output_path=output_path,
            stdout=stdout,
            stderr=stderr,
            status=status,

            num_bytes=num_bytes,
            num_files=num_files,
            num_dirs=num_dirs,
            **timer.stats,
        )


class ArchiveBoxDefaultExtractor(ArchiveBoxBaseExtractor, SingletonModel):
    singleton_instance_id = 1

    id = models.AutoField(default=singleton_instance_id, primary_key=True)

    DEPENDENCY = ArchiveBoxDefaultDependency

    ENABLED = models.BooleanField(default=True, editable=True)

    class Meta:
        abstract = False
        app_label = 'defaults'
        verbose_name = 'Default Configuration: Extractors'
