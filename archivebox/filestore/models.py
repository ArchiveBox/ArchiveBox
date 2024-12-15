import mimetypes
import uuid
from datetime import timedelta
from pathlib import Path
from django.db import models
from django.conf import settings
from django.utils import timezone

from archivebox import DATA_DIR
from archivebox.misc.hashing import get_dir_info, hash_file
from base_models.abid import DEFAULT_ABID_URI_SALT
from base_models.models import ABIDModel, ABIDField, get_or_create_system_user_pk


class File(ABIDModel):
    abid_prefix = 'fil_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.path'
    abid_subtype_src = 'self.mime_type'
    abid_rand_src = 'self.id'
    abid_salt: str = DEFAULT_ABID_URI_SALT           # combined with self.uri to anonymize hashes on a per-install basis (default is shared globally with all users, means everyone will hash ABC to -> 123 the same around the world, makes it easy to share ABIDs across installs and see if they are for the same URI. Change this if you dont want your hashes to be guessable / in the same hash space as all other users)
    abid_drift_allowed: bool = False        
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, null=False)
    abid = ABIDField(prefix=abid_prefix)

    created_at = models.DateTimeField(default=timezone.now, null=False)
    modified_at = models.DateTimeField(default=timezone.now, null=False)
    created_by = models.ForeignKey(settings.USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk)
    
    class StatusChoices(models.TextChoices):
        UNLOCKED = 'unlocked'
        LOCKED = 'locked'
    
    status = models.CharField(max_length=16, choices=StatusChoices.choices, default=StatusChoices.UNLOCKED, null=False)
    retry_at = models.DateTimeField(default=None, null=True)
    version = models.CharField(max_length=16, default='unknown', null=False)
    
    file = models.FileField(null=False)
    
    basename = models.CharField(max_length=255, default=None, null=False)                     # e.g. 'index'
    extension = models.CharField(max_length=63, default='', null=False)                       # e.g. 'html'
    mime_type = models.CharField(max_length=63, default=None, null=False, db_index=True)      # e.g. 'inode/directory' or 'text/html'
    num_subpaths = models.IntegerField(default=None, null=False)                              # e.g. 3
    num_bytes = models.IntegerField(default=None, null=False)                                 # e.g. 123456
    
    sha256 = models.CharField(max_length=64, default=None, null=False, db_index=True)    # e.g. '5994471abb01112afcc1815994471abb01112afcc1815994471abb01112afcc181'
    # blake3 = models.CharField(max_length=64, default=None, null=False, db_index=True)  # e.g. '5994471abb01112afcc1815994471abb01112afcc1815994471abb01112afcc181'
    
    DIR = 'inode/directory'

    @classmethod
    def release_expired_locks(cls):
        cls.objects.filter(status='locked', retry_at__lt=timezone.now()).update(status='unlocked', retry_at=None)

    @property
    def parent(self) -> 'File':
        return File.objects.get(path=str(self.PATH.parent)) or File(path=str(self.PATH.parent))
    
    @property
    def relpath(self) -> Path:
        return Path(self.file.name)
    
    @property
    def abspath(self) -> Path:
        return DATA_DIR / self.file.name

    def save(self, *args, **kwargs):
        assert self.abspath.exists()
        
        if self.abspath.is_dir():
            self.basename = self.relpath.name
            self.extension = ''
            self.mime_type = self.DIR
            dir_info = get_dir_info(self.abspath)
            self.num_subpaths = dir_info['.']['num_subpaths']
            self.num_bytes = dir_info['.']['num_bytes']
            self.hash_sha256 = dir_info['.']['hash_sha256']
            # TODO: hash_blake3 = dir_info['.']['hash_blake3']
        else:
            self.basename = self.relpath.name
            self.extension = self.relpath.suffix
            self.mime_type = mimetypes.guess_type(self.abspath)[0]
            self.num_bytes = self.abspath.stat().st_size
            self.hash_sha256, self.hash_blake3 = hash_file(self.abspath)
        super().save(*args, **kwargs)
            

    def acquire_lock(self, timeout_seconds: int = 60):
        self.status = 'locked'
        self.retry_at = timezone.now() + timedelta(seconds=timeout_seconds)
        self.save()

    def release_lock(self):
        self.status = 'unlocked'
        self.retry_at = None
        self.save()

    def move_to(self, new_path: Path):
        if str(new_path).startswith(str(DATA_DIR)):
            new_relpath = new_path.relative_to(DATA_DIR)
            new_abspath = new_path
        else:
            new_relpath = new_path
            new_abspath = DATA_DIR / new_path
            
        new_abspath.parent.mkdir(parents=True, exist_ok=True)
        self.abspath.rename(new_abspath)
        self.file.name = new_relpath
        self.save()
