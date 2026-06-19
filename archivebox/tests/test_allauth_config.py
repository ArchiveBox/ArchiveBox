import pytest


def test_allauth_config_defaults():
    from archivebox.config.allauth import AllauthConfig

    cfg = AllauthConfig()
    assert cfg.ALLAUTH_ENABLED is False
    assert cfg.SOCIALACCOUNT_ENABLED is False
    assert cfg.REGISTRATION_ENABLED is True
    assert cfg.REGISTRATION_MODE == "open"
    assert cfg.EMAIL_VERIFICATION == "none"
    assert cfg.DEFAULT_USER_PERMISSIONS == "readonly"


def test_allauth_config_from_env(monkeypatch):
    monkeypatch.setenv("ALLAUTH_ENABLED", "true")
    monkeypatch.setenv("REGISTRATION_MODE", "approval")
    from importlib import reload
    import archivebox.config.allauth as m

    reload(m)
    cfg = m.AllauthConfig()
    assert cfg.ALLAUTH_ENABLED is True
    assert cfg.REGISTRATION_MODE == "approval"


def test_registration_mode_validation():
    from archivebox.config.allauth import AllauthConfig
    import pytest

    with pytest.raises(Exception):
        AllauthConfig(REGISTRATION_MODE="invalid")
