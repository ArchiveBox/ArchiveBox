import pytest
from pydantic import ValidationError


def test_allauth_config_defaults():
    from archivebox.config.allauth import AllauthConfig

    cfg = AllauthConfig()
    assert cfg.ALLAUTH_ENABLED is False
    assert cfg.SOCIALACCOUNT_ENABLED is False
    assert cfg.REGISTRATION_ENABLED is True
    assert cfg.REGISTRATION_MODE == "open"
    assert cfg.EMAIL_VERIFICATION == "none"
    assert cfg.DEFAULT_USER_PERMISSIONS == "none"


def test_allauth_config_from_env(monkeypatch):
    monkeypatch.setenv("ALLAUTH_ENABLED", "true")
    monkeypatch.setenv("REGISTRATION_MODE", "approval")
    from archivebox.config.common import ArchiveBoxSourceSettings

    cfg = ArchiveBoxSourceSettings()
    assert cfg.ALLAUTH_ENABLED is True
    assert cfg.REGISTRATION_MODE == "approval"


def test_registration_mode_validation():
    from archivebox.config.allauth import AllauthConfig

    with pytest.raises(ValidationError):
        AllauthConfig(REGISTRATION_MODE="invalid")
