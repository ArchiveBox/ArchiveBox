"""Optional browser authentication; these settings never enter capture hooks."""

from typing import Literal, Self

from pydantic import Field, PrivateAttr, model_validator

from archivebox.config.configset import BaseConfigSet


class AllauthConfig(BaseConfigSet):
    toml_section_header: str = "ALLAUTH_CONFIG"
    _scope: str = PrivateAttr(default="server")

    ALLAUTH_ENABLED: bool = False
    REGISTRATION_ENABLED: bool = False
    REGISTRATION_MODE: Literal["open", "approval"] = "approval"
    DEFAULT_USER_PERMISSIONS: Literal["none", "admin"] = "none"
    EMAIL_VERIFICATION: Literal["none", "optional", "mandatory"] = "none"
    SOCIALACCOUNT_PROVIDERS: dict = Field(default_factory=dict)
    SOCIALACCOUNT_EMAIL_AUTHENTICATION: bool = False
    SOCIALACCOUNT_EMAIL_AUTO_CONNECT: bool = False
    EMAIL_HOST: str = ""
    EMAIL_PORT: int = 587
    EMAIL_HOST_USER: str = ""
    EMAIL_HOST_PASSWORD: str = ""
    EMAIL_USE_TLS: bool = True
    EMAIL_USE_SSL: bool = False
    DEFAULT_FROM_EMAIL: str = "webmaster@localhost"

    @model_validator(mode="after")
    def validate_email_linking(self) -> Self:
        if self.EMAIL_USE_SSL and self.EMAIL_USE_TLS:
            raise ValueError("Set only one of EMAIL_USE_SSL and EMAIL_USE_TLS")
        if self.SOCIALACCOUNT_EMAIL_AUTO_CONNECT and not self.SOCIALACCOUNT_EMAIL_AUTHENTICATION:
            raise ValueError("SOCIALACCOUNT_EMAIL_AUTO_CONNECT requires SOCIALACCOUNT_EMAIL_AUTHENTICATION=True and trusted providers")
        return self
