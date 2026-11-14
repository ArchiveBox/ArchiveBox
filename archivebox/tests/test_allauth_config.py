import pytest
from pydantic import ValidationError


def test_allauth_is_explicit_and_registration_is_closed():
    from archivebox.config.common import get_config, get_all_configs

    config = get_config()
    assert config.ALLAUTH_ENABLED is False
    assert config.REGISTRATION_ENABLED is False
    assert config.DEFAULT_USER_PERMISSIONS == "none"
    sections = get_all_configs()
    assert "ALLAUTH_CONFIG" in sections
    assert all(section.model_dump()["toml_section_header"] == name for name, section in sections.items())


def test_cli_writes_allauth_keys_to_their_own_section(initialized_archive):
    from archivebox.config.configset import CaseConfigParser
    from archivebox.tests.conftest import run_archivebox_cmd

    result = run_archivebox_cmd(
        ["config", "--set", "REGISTRATION_ENABLED=True", "EMAIL_PORT=2525"],
        cwd=initialized_archive,
        default_cli_env=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    config = CaseConfigParser()
    config.read(initialized_archive / "ArchiveBox.conf")
    assert config.getboolean("ALLAUTH_CONFIG", "REGISTRATION_ENABLED")
    assert config.getint("ALLAUTH_CONFIG", "EMAIL_PORT") == 2525
    assert not config.has_option("SHELL_CONFIG", "REGISTRATION_ENABLED")


def test_provider_credentials_are_redacted():
    from archivebox.config.common import redact_sensitive_config

    assert redact_sensitive_config({"SOCIALACCOUNT_PROVIDERS": {"saml": {"private_key": "private"}}}) == {
        "SOCIALACCOUNT_PROVIDERS": "********",
    }


def test_sso_config_does_not_reach_capture_hooks():
    from archivebox.config.common import filter_crawl_env

    env = {"ALLAUTH_ENABLED": "true", "SOCIALACCOUNT_PROVIDERS": "private", "EMAIL_HOST_PASSWORD": "private", "PATH": "/bin"}
    assert filter_crawl_env(env) == {"PATH": "/bin"}


def test_registration_modes_are_real_policies():
    from archivebox.config.allauth import AllauthConfig

    with pytest.raises(ValidationError):
        AllauthConfig.model_validate({"REGISTRATION_MODE": "invite"})


def test_email_autoconnect_requires_explicit_email_authentication():
    from archivebox.config.allauth import AllauthConfig

    with pytest.raises(ValidationError):
        AllauthConfig(SOCIALACCOUNT_EMAIL_AUTO_CONNECT=True)
