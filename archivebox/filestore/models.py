# import mimetypes
# import uuid

# from django.db import models
# from django.conf import settings
# from django.utils import timezone

# from archivebox import DATA_DIR
# from archivebox.misc.hashing import get_dir_info, hash_file
# from base_models.abid import DEFAULT_ABID_URI_SALT
# from base_models.models import ABIDModel, ABIDField, get_or_create_system_user_pk


# class File(ABIDModel):
#     abid_prefix = 'fil_'
#     abid_ts_src = 'self.created_at'
#     abid_uri_src = 'self.path'
#     abid_subtype_src = 'self.mime_type'
#     abid_rand_src = 'self.id'
#     abid_salt: str = DEFAULT_ABID_URI_SALT           # combined with self.uri to anonymize hashes on a per-install basis (default is shared globally with all users, means everyone will hash ABC to -> 123 the same around the world, makes it easy to share ABIDs across installs and see if they are for the same URI. Change this if you dont want your hashes to be guessable / in the same hash space as all other users)
#     abid_drift_allowed: bool = False        
    
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, null=False)
#     abid = ABIDField(prefix=abid_prefix)

#     created_at = models.DateTimeField(default=timezone.now, null=False)
#     modified_at = models.DateTimeField(default=timezone.now, null=False)
#     created_by = models.ForeignKey(settings.USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk)
    
#     path = models.FilePathField(path=str(DATA_DIR), recursive=True, allow_files=True, allow_folders=True, db_index=True, unique=True)
    
#     basename = models.CharField(max_length=255, default=None, null=False)                     # e.g. 'index'
#     extension = models.CharField(max_length=63, default='', null=False)                       # e.g. 'html'
#     mime_type = models.CharField(max_length=63, default=None, null=False, db_index=True)      # e.g. 'inode/directory' or 'text/html'
#     num_subpaths = models.IntegerField(default=None, null=False)                              # e.g. 3
#     num_bytes = models.IntegerField(default=None, null=False)                                 # e.g. 123456
    
#     hash_sha256 = models.CharField(max_length=64, default=None, null=False, db_index=True)    # e.g. '5994471abb01112afcc1815994471abb01112afcc1815994471abb01112afcc181'
#     # hash_blake3 = models.CharField(max_length=64, default=None, null=False, db_index=True)  # e.g. '5994471abb01112afcc1815994471abb01112afcc1815994471abb01112afcc181'
    
#     DIR = 'inode/directory'


#     @property
#     def parent(self) -> 'File':
#         return File.objects.get(path=self.path.parent) or File(path=self.path.parent)

#     def save(self, *args, **kwargs):
#         assert self.path.exists()
        
#         if self.path.is_dir():
#             self.basename = self.path.name
#             self.extension = ''
#             self.mime_type = self.DIR
#             dir_info = get_dir_info(self.path)
#             self.num_subpaths = dir_info['.']['num_subpaths']
#             self.num_bytes = dir_info['.']['num_bytes']
#             self.hash_sha256 = dir_info['.']['hash_sha256']
#             # TODO: hash_blake3 = dir_info['.']['hash_blake3']
#         else:
#             self.basename = self.path.name
#             self.extension = self.path.suffix
#             self.mime_type = mimetypes.guess_type(self.path)[0]
#             self.num_bytes = self.path.stat().st_size
#             self.hash_sha256, self.hash_blake3 = hash_file(self.path)
#         super().save(*args, **kwargs)
            
