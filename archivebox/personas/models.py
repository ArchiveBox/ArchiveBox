# from django.db import models

# from django.conf import settings


# class Persona(models.Model):
#     """Aka a "SessionType", its a template for a crawler browsing session containing some config."""

#     id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    
#     created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False)
#     created_at = AutoDateTimeField(default=None, null=False, db_index=True)
#     modified_at = models.DateTimeField(auto_now=True)
    
#     name = models.CharField(max_length=100, blank=False, null=False, editable=False)
    
#     persona_dir = models.FilePathField(path=settings.PERSONAS_DIR, allow_files=False, allow_folders=True, blank=True, null=False, editable=False)
#     config = models.JSONField(default=dict)
#     # e.g. {
#     #    USER_AGENT: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
#     #    COOKIES_TXT_FILE: '/path/to/cookies.txt',
#     #    CHROME_USER_DATA_DIR: '/path/to/chrome/user/data/dir',
#     #    CHECK_SSL_VALIDITY: False,
#     #    SAVE_ARCHIVE_DOT_ORG: True,
#     #    CHROME_BINARY: 'chromium'
#     #    ...
#     # }
#     # domain_allowlist = models.CharField(max_length=1024, blank=True, null=False, default='')
#     # domain_denylist = models.CharField(max_length=1024, blank=True, null=False, default='')
    
#     class Meta:
#         app_label = 'personas'
#         verbose_name = 'Session Type'
#         verbose_name_plural = 'Session Types'
#         unique_together = (('created_by', 'name'),)
    

#     def clean(self):
#         self.persona_dir = settings.PERSONAS_DIR / self.name
#         assert self.persona_dir == settings.PERSONAS_DIR / self.name, f'Persona dir {self.persona_dir} must match settings.PERSONAS_DIR / self.name'
        
        
#         # make sure config keys all exist in FLAT_CONFIG
#         # make sure config values all match expected types
#         pass
        
#     def save(self, *args, **kwargs):
#         self.full_clean()
        
#         # make sure basic file structure is present in persona_dir:
#         # - PERSONAS_DIR / self.name / 
#         #   - chrome_profile/
#         #   - chrome_downloads/
#         #   - chrome_extensions/
#         #   - cookies.txt
#         #   - auth.json
#         #   - config.json    # json dump of the model
        
#         super().save(*args, **kwargs)
