from django.db import models
from django.utils.functional import cached_property

from solo.models import SingletonModel

from archivebox.plugins.defaults.models import (
    ArchiveBoxDefaultDependency,
    ArchiveBoxDefaultExtractor,
    BashEnvironmentDependency,
    PipEnvironmentDependency,
)


class GalleryDLDependency(ArchiveBoxDefaultDependency, SingletonModel):
    NAME = 'GALLERYDL'
    LABEL = "GalleryDL"
    REQUIRED = False

    PARENT_DEPENDENCIES = [
        BashEnvironmentDependency,
        PipEnvironmentDependency,
    ]

    BIN_DEPENDENCIES = ['gallery-dl']
    APT_DEPENDENCIES = []
    BREW_DEPENDENCIES = []
    PIP_PACKAGES = ['gallery-dl']
    NPM_PACKAGES = []

    DEFAULT_BINARY = 'gallery-dl'
    DEFAULT_START_CMD = None
    DEFAULT_ARGS = []
    VERSION_CMD = '{BINARY} --version'

    ENABLED = models.BooleanField(default=True)
    BINARY = models.CharField(max_length=255, default='gallery-dl')

    WORKERS = models.IntegerField(default='1')


class GalleryDLExtractor(ArchiveBoxDefaultExtractor, SingletonModel):
    NAME = 'GALLERYDL'
    LABEL = 'gallery-dl'

    DEPENDENCY = GalleryDLDependency.get_solo()

    # https://github.com/mikf/gallery-dl
    DEFAULT_CMD = [
        '{DEPENDENCY.BINARY}',
        '{ARGS}'
        '{url}',
    ]
    DEFAULT_ARGS = [
        '--timeout', self.TIMEOUT.format(**config),
        '--cookies', self.COOKIES_TXT.format(**config),
        '--user-agent', self.COOKIES_TXT.format(**config),
        '--verify', self.CHECK_SSL_VALIDITY.format(**config),
    ]

    ENABLED = models.BooleanField(default=True)

    CMD = models.CharField(max_length=255, default=DEFAULT_CMD)
    ARGS = models.CSVField(max_length=255, default=DEFAULT_ARGS)
    
    TIMEOUT = models.CharField(max_length=255, default='{TIMEOUT}')
    USER_AGENT = models.CharField(max_length=255, default='{USER_AGENT}')
    COOKIES_TXT = models.CharField(max_length=255, default='{COOKIES_TXT}')
    CHECK_SSL_VALIDITY = models.CharField(default='{CHECK_SSL_VALIDITY}')

    # @task
    # @requires_config('HOSTNAME', 'TIMEOUT', 'USER_AGENT', 'CHECK_SSL_VALIDITY')
    def extract(self, url: str, out_dir: Path, config: ConfigDict):
        if not self.ENABLED:
            return

        extractor_dir = self.create_extractor_directory(out_dir)

        cmd = [
            self.CMD,
            url,
            '--timeout', self.TIMEOUT.format(**config),
            '--cookies', self.COOKIES_TXT.format(**config),
            '--user-agent', self.COOKIES_TXT.format(**config),
            '--verify', self.CHECK_SSL_VALIDITY.format(**config),
            *split_args(self.ARGS.format(**config)),
        ]

        status, stdout, stderr, output_path = 'failed', '', '', None
        try:
            proc, timer, errors = self.DEPENDENCY.run(cmd, cwd=extractor_dir, timeout=self.GALLERYDL_TIMEOUT)
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
            cmd_version=self.DEPENDENCY.bin_version,
            cmd_path=self.DEPENDENCY.bin_path,
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
