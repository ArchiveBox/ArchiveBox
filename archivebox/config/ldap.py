__package__ = "archivebox.config"

from typing import Optional
from pydantic import Field

from archivebox.config.configset import BaseConfigSet


class LDAPConfig(BaseConfigSet):
    """
    LDAP authentication configuration.

    Only loads and validates if django-auth-ldap is installed.
    These settings integrate with Django's LDAP authentication backend.
    """
    toml_section_header: str = "LDAP_CONFIG"

    LDAP_ENABLED: bool = Field(default=False)
    LDAP_SERVER_URI: Optional[str] = Field(default=None)
    LDAP_BIND_DN: Optional[str] = Field(default=None)
    LDAP_BIND_PASSWORD: Optional[str] = Field(default=None)
    LDAP_USER_BASE: Optional[str] = Field(default=None)
    LDAP_USER_FILTER: str = Field(default="(uid=%(user)s)")
    LDAP_USERNAME_ATTR: str = Field(default="username")
    LDAP_FIRSTNAME_ATTR: str = Field(default="givenName")
    LDAP_LASTNAME_ATTR: str = Field(default="sn")
    LDAP_EMAIL_ATTR: str = Field(default="mail")
    LDAP_CREATE_SUPERUSER: bool = Field(default=False)

    def validate_ldap_config(self) -> tuple[bool, str]:
        """
        Validate that all required LDAP settings are configured.

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.LDAP_ENABLED:
            return True, ""

        required_fields = [
            "LDAP_SERVER_URI",
            "LDAP_BIND_DN",
            "LDAP_BIND_PASSWORD",
            "LDAP_USER_BASE",
        ]

        missing = [field for field in required_fields if not getattr(self, field)]

        if missing:
            return False, f"LDAP_* config options must all be set if LDAP_ENABLED=True\nMissing: {', '.join(missing)}"

        return True, ""


# Singleton instance
LDAP_CONFIG = LDAPConfig()
