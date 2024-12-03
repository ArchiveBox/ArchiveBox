import hashlib
import mimetypes
import os

from typing import ClassVar
from datetime import timedelta
from zipfile import Path

from django.utils import timezone

from core.models import ArchiveResult

import abx
import archivebox

class Extractor:
    # static class variables
    name: ClassVar[str] = 'ytdlp'
    verbose_name: ClassVar[str] = 'YT-DLP'
    binaries: ClassVar[tuple[str, ...]] = ()
    daemons: ClassVar[tuple[str, ...]] = ()
    timeout: ClassVar[int] = 60
    
    # instance variables
    ARCHIVERESULT: ArchiveResult
    CONFIG: dict[str, object]
    BINARIES: dict[str, object]
    DAEMONS: dict[str, object]
    
    def __init__(self, archiveresult: ArchiveResult, extra_config: dict | None=None):
        assert archiveresult.pk, 'ArchiveResult must be saved to DB before it can be extracted'
        self.archiveresult = self.ARCHIVERESULT = archiveresult
        self.CONFIG = archivebox.pm.hook.get_SCOPE_CONFIG(archiveresult=self.archiveresult, extra=extra_config)
        all_binaries = abx.as_dict(archivebox.pm.hook.get_BINARIES())
        all_daemons = abx.as_dict(archivebox.pm.hook.get_DAEMONS())
        self.BINARIES = {
            binary_name: all_binaries[binary_name]
            for binary_name in self.binaries
        }
        self.DAEMONS = {
            daemon_name: all_daemons[daemon_name]
            for daemon_name in self.daemons
        }

    def extract(self, config: dict | None=None) -> 'ArchiveResult':
        """
        - making sure any binaries the extractor depends on are installed and loaded
        - creating a new temporary working directory under the snapshot dir to hold extractor output
        - setting up a timer signal to kill the extractor if it runs too long
        - passing the extractor the URLs, temporary working directory, and config dict of options
        - running the extractor in a shell subprocess and collecting stdout/stderr
        - capturing the extractor's exit code
        - if extractor exits with 29 (RetryError), it should set the status to 'BACKOFF' and set retry_at to a datetime in the future
        - if extractor exits with 50 (NotApplicable), it should set the status to 'SKIPPED', and set retry_at to None
        - setting the correct permissions and ownership on all the output files
        - generating the merkle tree of all the output files and their hashes
        - generating a thumbnail of the main output (or collecting one provided by the extractor)
        - detecting any special outputs files that need to be parsed for other parts of the system (content-types? )
            - metadata.json -> ArchiveResult.output_json
            - outlinks.jsonl -> ArchiveResult.output_links
            - search_texts.txt -> ArchiveResult.index_texts
            - .merkle.json -> ArchiveResult.output_files
            - videos.jsonl -> ArchiveResult.output_videos
            - audios.jsonl -> ArchiveResult.output_audios
            - images.jsonl -> ArchiveResult.output_images
            - htmls.jsonl -> ArchiveResult.output_htmls
        - saving all the result metadata to the ArchiveResult in the database
        """
        
        archiveresult = self.ARCHIVERESULT
        # config = get_scope_config(archiveresult=archiveresult.snapshot.url, env=...)
        
        self.before_extract()

        error = Exception('Failed to start extractor')
        stdout = ''
        stderr = ''
        try:
            proc = archiveresult.EXTRACTOR.spawn(url=archiveresult.snapshot.url, binaries=binaries, daemons=daemons, cwd=cwd, config=config)
            stdout, stderr = proc.communicate()
            error = None
        except Exception as err:
            error = err
        finally:
            self.after_extract(error=error)
        
        return archiveresult
        
    def should_extract(self):
        if self.archiveresult.snapshot.url.startswith('https://youtube.com/'):
            return True
        return False

    def load_binaries(self):
        return {
            bin_name: binary.load()
            for bin_name, binary in self.BINARIES.items()
        }
    
    def load_daemons(self):
        return {
            daemon_name: daemon.load()
            for daemon_name, daemon in self.DAEMONS.items()
        }
        
    def output_dir_name(self):
        # e.g. 'ytdlp'
        return f'{self.name}'
    
    @property
    def OUTPUT_DIR(self):
        return self.archiveresult.snapshot_dir / self.output_dir_name()
    
    def before_extract(self):
        # create self.archiveresult.snapshot_dir / self.archiveresult.extractor / dir
        # chown, chmod, etc.
        binaries = self.load_binaries()
        daemons = self.load_daemons()
        cmd = self.archiveresult.EXTRACTOR.get_cmd(binaries=binaries, daemons=daemons)
        cmd_version = self.archiveresult.EXTRACTOR.get_cmd_version(binaries=binaries, daemons=daemons)
        
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(self.OUTPUT_DIR, 0o755)
        self.archiveresult.status = self.archiveresult.StatusChoices.STARTED
        self.archiveresult.retry_at = timezone.now() + timedelta(seconds=self.timeout)
        self.archiveresult.start_ts = timezone.now()
        self.archiveresult.end_ts = None
        self.archiveresult.output = None
        self.archiveresult.output_path = str(self.OUTPUT_DIR.relative_to(self.archiveresult.snapshot_dir))
        self.archiveresult.cmd = cmd
        self.archiveresult.cmd_version = cmd_version
        self.archiveresult.machine = Machine.objects.get_current()
        self.archiveresult.iface = NetworkInterface.objects.get_current()
        self.archiveresult.save()
        self.archiveresult.write_indexes()
    
    def extract(self, url: str, binaries: dict, daemons: dict, cwd: Path, config: dict):
        proc = subprocess.run(self.archiveresult.cmd, cwd=self.archiveresult.cwd, env=os.environ.update(binaries), timeout=self.timeout, shell=True, capture_output=True, text=True)
        self.archiveresult.stdout = proc.stdout
        self.archiveresult.stderr = proc.stderr
        self.archiveresult.returncode = proc.returncode
        self.archiveresult.save()
        self.archiveresult.write_indexes()
        
    def determine_status(self):
        if self.archiveresult.returncode == 29:
            return self.archiveresult.StatusChoices.BACKOFF, timezone.now() + timedelta(seconds=self.timeout)
        elif self.archiveresult.returncode == 50:
            return self.archiveresult.StatusChoices.SKIPPED, None
        else:
            return self.archiveresult.StatusChoices.FAILED, None

    def collect_outputs(self, cwd: Path):
        for file in cwd.rglob('*'):
            path = file.relative_to(cwd)
            os.chmod(file, 0o644)
            #os.chown(file, ARCHIVEBOX_UID, ARCHIVEBOX_GID)
            
            self.archiveresult.outputs.append({
                'type': 'FILE',
                'path': file.relative_to(cwd),
                'size': file.stat().st_size,
                'ext': file.suffix,
                'mimetype': mimetypes.guess_type(file)[0],
                'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                'blake3': hashlib.blake3(file.read_bytes()).hexdigest(),
                'created_at': file.stat().st_ctime,
                'modified_at': file.stat().st_mtime,
                'symlinks': [
                    'screenshot.png',
                    'example.com',
                ]
            })
            outlinks = parse_outlinks(file)
            if outlinks:
                self.archiveresult.outputs.append({
                    'type': 'OUTLINK',
                    'url': outlink.target,
                    'selector': outlink.selector,
                    'text': outlink.text,
                })

            if path.endswith('favicon.ico'):
                self.archiveresult.outputs.append({
                    'type': 'FAVICON',
                    'symlinks': {
                        'favicon': output_file['path'],
                        'favicon.ico': output_file['path'],
                        'favicon.png': output_file['path'].with_suffix('.png'),
                    },
                    'path': output_file['path'],
                })
            if path.endswith('.pdf'):
                self.archiveresult.outputs.append({
                    'type': 'PDF',
                    'path': file.relative_to(cwd),
                    ''
                })
                
            if 'text/plain' in mimetypes.guess_type(file):
                self.archiveresult.outputs.append({
                    'type': 'SEARCHTEXT',
                    'path': file.relative_to(self.archiveresult.OUTPUT_DIR),
                    'archiveresult_id': self.archiveresult.id,
                })
    
    def after_extract(self, error: Exception | None=None):
        status, retry_at = self.determine_status()
        
        self.archiveresult.outputs = []
        
        
        self.archiveresult.error = f'{type(error).__name__}: {error}' if error else None
        self.archiveresult.status = self.archiveresult.StatusChoices.FAILED if error else self.archiveresult.StatusChoices.SUCCEEDED
        self.archiveresult.retry_at = None
        self.archiveresult.end_ts = timezone.now()
        self.archiveresult.output = self.archiveresult.outputs[0].path
        self.archiveresult.save()
        self.archiveresult.write_indexes()
    