"""
django-allauth integration for ArchiveBox.

Provides social login, email/password auth, and configurable user registration
as a replacement for the default admin-only login flow.

Only activates if ALLAUTH_ENABLED=True in config and django-allauth is installed.

To install allauth support:
    pip install archivebox[allauth]
    # or
    uv add "django-allauth[socialaccount]>=65.0"

To configure social providers, set SOCIALACCOUNT_PROVIDERS in ArchiveBox.conf:
    [ALLAUTH_CONFIG]
    ALLAUTH_ENABLED = true
    SOCIALACCOUNT_ENABLED = true
    REGISTRATION_MODE = open     # open | invite | approval
    EMAIL_VERIFICATION = none    # none | optional | mandatory

    SOCIALACCOUNT_PROVIDERS = {"github": {"APP": {"client_id": "...", "secret": "..."}}}
"""

__package__ = "archivebox.auth"
