from solo.models import SingletonModel


class GalleryDLDependency(SingletonModel):
    GALLERYDL_ENABLED = models.BooleanField(default=True)
    GALLERYDL_BINARY = models.CharField(max_length=255, default='gallery-dl')

    def __str__(self):
        return "GalleryDL Dependency Configuration"

    class Meta:
        verbose_name = "GalleryDL Dependency Configuration"

    @cached_property
    def bin_path(self):
        return bin_path(self.GALLERYDL_BINARY)

    @cached_property
    def bin_version(self):
        return bin_version(self.bin_path)

    @cached_property
    def is_valid(self):
        return self.bin_path and self.bin_version

    @cached_property
    def enabled(self):
        return self.GALLERYDL_ENABLED and self.is_valid


    def pretty_version(self):
        if self.enabled:
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



class GalleryDLExtractor(SingletonModel):
    GALLERYDL_EXTRACTOR_NAME = 'gallerydl'

    SAVE_GALLERYDL = models.BooleanField(default=True)

    GALLERYDL_DEPENDENCY = GalleryDLDependency.get_solo()

    # https://github.com/mikf/gallery-dl
    GALLERYDL_ARGS = models.CSVField(max_length=255, default=[])
    GALLERYDL_TIMEOUT = models.IntegerField(default=lambda c: c['TIMEOUT'])
    GALLERYDL_USER_AGENT = models.CharField(max_length=255, default='{USER_AGENT}')
    GALLERYDL_COOKIES_TXT = models.CharField(max_length=255, default='{COOKIES_TXT}')

    ALIASES = {
        'SAVE_GALLERYDL': ('USE_GALLERYDL', 'FETCH_GALLERYDL'),
    }

    @cached_property
    def enabled(self):
        return self.SAVE_GALLERYDL and self.GALLERYDL_DEPENDENCY.is_valid


    def __str__(self):
        return "GalleryDL Extractor Configuration"

    class Meta:
        verbose_name = "GalleryDL Extractor Configuration"

    def __json__(self):
        return {
            'SAVE_GALLERYDL': self.SAVE_GALLERYDL,
            'GALLERYDL_DEPENDENCY': self.GALLERYDL_DEPENDENCY.__json__(),
            'GALLERYDL_ARGS': self.GALLERYDL_ARGS,
            'GALLERYDL_TIMEOUT': self.GALLERYDL_TIMEOUT,
            'GALLERYDL_USER_AGENT': self.GALLERYDL_USER_AGENT,
            'GALLERYDL_COOKIES_TXT': self.GALLERYDL_COOKIES_TXT,
        }

    def validate(self):
        assert 5 < self.GALLERYDL_TIMEOUT, 'GALLERYDL_TIMEOUT must be at least 5 seconds'
        # assert Path(self.GALLERYDL_COOKIES_TXT).exists()
        # TODO: validate user agent with uaparser
        # TODO: validate args, cookies.txt?


    def save(self, *args, **kwargs):
        self.validate()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            emit_event({'type': 'GalleryDLExtractor.save', 'diff': self.__json__(), 'kwargs': kwargs})
            # potential consumers of this event:
            #    - event logger: write to events.log
            #    - config file updater: writes to ArchiveBox.conf
            #    - supervisor: restarts relevant dependencies/extractors
            #    - etc...

        return result


    def create_extractor_directory(self, parent_dir: Path):
        return subdir = (parent_dir / self.GALLERYDL_EXTRACTOR_NAME).mkdir(exist_ok=True)

    def should_extract(self, parent_dir: Path):
        existing_files = (parent_dir / self.GALLERYDL_EXTRACTOR_NAME).glob('*')
        return not existing_files


    def extract(self, url: str, out_dir: Path):
        if not self.enabled:
            return

        extractor_dir = self.create_extractor_directory(out_dir)

        cmd = [
            self.GALLERYDL_DEPENDENCY.bin_path,
            url,
            '--timeout', GALLERYDL_TIMEOUT,
            '--cookies', GALLERYDL_COOKIES_TXT,
            '--user-agent', GALLERYDL_USER_AGENT,
            '--verify', config.CHECK_SSL_VALIDITY
            *self.GALLERYDL_ARGS,
        ]

        status, stdout, stderr, output_path = 'failed', '', '', None
        timer = TimedProgress(timeout, prefix='      ')
        try:
            proc = run(cmd, cwd=extractor_dir, timeout=self.GALLERYDL_TIMEOUT, text=True)
            stdout, stderr = proc.stdout, proc.stderr
            
            if 'ERROR: Unsupported URL' in stderr:
                hints = ('gallery-dl doesnt support this type of url yet',)
                raise ArchiveError('Failed to save gallerydl', hints)

            if proc.returncode == 0 and 'finished' in stdout:
                output_path = extractor_dir / 'index.html'
                status = 'succeeded'

        except Exception as err:
            stderr += err
        finally:
            timer.end()

        num_bytes, num_dirs, num_files = get_dir_size(extractor_dir)

        return ArchiveResult(
            status=status,

            cmd=cmd,
            pwd=str(out_dir),
            cmd_version=self.GALLERYDL_DEPENDENCY.bin_version,
            cmd_path=self.GALLERYDL_DEPENDENCY.bin_path,
            cmd_hostname=config.HOSTNAME,

            output_path=output_path,
            stdout=stdout,
            stderr=stderr,

            num_bytes=num_bytes,
            num_files=num_files,
            num_dirs=num_dirs,
            **timer.stats,
        )
