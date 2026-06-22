__package__ = "archivebox.config"

from pydantic import Field, PrivateAttr, field_validator

from archivebox.config.configset import BaseConfigSet


class AllauthConfig(BaseConfigSet):
    """
    django-allauth authentication configuration.

    Only activates if ALLAUTH_ENABLED=True and django-allauth is installed.
    """

    toml_section_header: str = "ALLAUTH_CONFIG"
    _scope: str = PrivateAttr(default="server")

    ALLAUTH_ENABLED: bool = Field(default=False)
    SOCIALACCOUNT_ENABLED: bool = Field(default=False)
    REGISTRATION_ENABLED: bool = Field(default=True)
    REGISTRATION_MODE: str = Field(default="open")
    EMAIL_VERIFICATION: str = Field(default="none")
    DEFAULT_USER_PERMISSIONS: str = Field(default="none")
    SOCIALACCOUNT_PROVIDERS: dict = Field(default_factory=dict)

    # SECURITY: Auto-connecting social accounts by verified email is disabled by default.
    # When True, a social login whose provider-reported email matches an existing local
    # account will be silently linked to that account without user confirmation.
    # This creates an account-takeover risk if the OIDC/OAuth provider's email
    # verification is weak or if the provider itself is compromised.
    # Only enable this if you fully trust all configured social providers AND require
    # mandatory email verification (EMAIL_VERIFICATION=mandatory) in your setup.
    # See: https://docs.allauth.org/en/latest/socialaccount/configuration.html
    SOCIALACCOUNT_EMAIL_AUTO_CONNECT: bool = Field(default=False)

    @field_validator("REGISTRATION_MODE", mode="after")
    @classmethod
    def validate_registration_mode(cls, v: str) -> str:
        allowed = {"open", "invite", "approval"}
        if v not in allowed:
            raise ValueError(f"REGISTRATION_MODE must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("EMAIL_VERIFICATION", mode="after")
    @classmethod
    def validate_email_verification(cls, v: str) -> str:
        allowed = {"mandatory", "optional", "none"}
        if v not in allowed:
            raise ValueError(f"EMAIL_VERIFICATION must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("DEFAULT_USER_PERMISSIONS", mode="after")
    @classmethod
    def validate_default_user_permissions(cls, v: str) -> str:
        allowed = {"none", "admin"}
        if v not in allowed:
            raise ValueError(f"DEFAULT_USER_PERMISSIONS must be one of: {', '.join(sorted(allowed))}")
        return v
