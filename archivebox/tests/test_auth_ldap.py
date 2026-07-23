"""
LDAP authentication tests for ArchiveBox.

Tests LDAP configuration, validation, and integration with Django.
Per CLAUDE.md: NO MOCKS, NO SKIPS - all tests use real code paths.
"""

from importlib.util import find_spec

from archivebox.tests.conftest import run_archivebox_cmd


class TestLDAPConfig:
    """Test LDAP configuration loading and validation."""

    def test_ldap_config_defaults(self):
        """Test that LDAP config loads with correct defaults."""
        from archivebox.config.common import get_config

        # Check default values
        config = get_config()
        assert not config.LDAP_ENABLED
        assert config.LDAP_SERVER_URI is None
        assert config.LDAP_BIND_DN is None
        assert config.LDAP_BIND_PASSWORD is None
        assert config.LDAP_USER_BASE is None
        assert config.LDAP_USER_FILTER == "(uid=%(user)s)"
        assert config.LDAP_USERNAME_ATTR == "username"
        assert config.LDAP_FIRSTNAME_ATTR == "givenName"
        assert config.LDAP_LASTNAME_ATTR == "sn"
        assert config.LDAP_EMAIL_ATTR == "mail"
        assert not config.LDAP_CREATE_SUPERUSER

    def test_ldap_config_validation_disabled(self):
        """Test that validation passes when LDAP is disabled."""
        from archivebox.config.ldap import LDAPConfig

        config = LDAPConfig(LDAP_ENABLED=False)
        is_valid, error_msg = config.validate_ldap_config()

        assert is_valid
        assert error_msg == ""

    def test_ldap_config_validation_missing_fields(self):
        """Test that validation fails when required fields are missing."""
        from archivebox.config.ldap import LDAPConfig

        # Enable LDAP but don't provide required fields
        config = LDAPConfig(LDAP_ENABLED=True)
        is_valid, error_msg = config.validate_ldap_config()

        assert not is_valid
        assert "LDAP_* config options must all be set" in error_msg
        assert "LDAP_SERVER_URI" in error_msg
        assert "LDAP_BIND_DN" in error_msg
        assert "LDAP_BIND_PASSWORD" in error_msg
        assert "LDAP_USER_BASE" in error_msg

    def test_ldap_config_validation_complete(self):
        """Test that validation passes when all required fields are provided."""
        from archivebox.config.ldap import LDAPConfig

        config = LDAPConfig(
            LDAP_ENABLED=True,
            LDAP_SERVER_URI="ldap://ldap-test.localhost:389",
            LDAP_BIND_DN="cn=admin,dc=example,dc=com",
            LDAP_BIND_PASSWORD="password",
            LDAP_USER_BASE="ou=users,dc=example,dc=com",
        )
        is_valid, error_msg = config.validate_ldap_config()

        assert is_valid
        assert error_msg == ""

    def test_ldap_config_in_get_config(self):
        """Test that LDAP_CONFIG is included in the typed config sections."""
        from archivebox.config.common import get_all_configs

        all_config = get_all_configs()
        assert "LDAP_CONFIG" in all_config
        assert all_config["LDAP_CONFIG"].__class__.__name__ == "LDAPConfig"


class TestLDAPIntegration:
    """Test LDAP integration with Django settings."""

    def test_django_settings_without_ldap_enabled(self):
        """Test that Django settings work correctly when LDAP is disabled."""
        # Import Django settings (LDAP_ENABLED should be False by default)
        from django.conf import settings

        # Should have default authentication backends
        assert "django.contrib.auth.backends.RemoteUserBackend" in settings.AUTHENTICATION_BACKENDS
        assert "django.contrib.auth.backends.ModelBackend" in settings.AUTHENTICATION_BACKENDS

        # LDAP backend should not be present when disabled
        ldap_backends = [b for b in settings.AUTHENTICATION_BACKENDS if "ldap" in b.lower()]
        assert len(ldap_backends) == 0, "LDAP backend should not be present when LDAP_ENABLED=False"

    def test_django_settings_with_ldap_enabled(self, initialized_archive):
        """Test the real enabled LDAP settings path with installed libraries."""
        assert find_spec("django_auth_ldap") is not None
        assert find_spec("ldap") is not None

        result = run_archivebox_cmd(
            [
                "manage",
                "shell",
                "-c",
                (
                    "from django.conf import settings; "
                    "print('LDAP_BACKENDS=' + ','.join(settings.AUTHENTICATION_BACKENDS)); "
                    "print('LDAP_SERVER_URI=' + settings.AUTH_LDAP_SERVER_URI)"
                ),
            ],
            cwd=initialized_archive,
            timeout=45,
            env={
                "LDAP_ENABLED": "True",
                "LDAP_SERVER_URI": "ldap://ldap-test.localhost:389",
                "LDAP_BIND_DN": "cn=admin,dc=example,dc=com",
                "LDAP_BIND_PASSWORD": "password",
                "LDAP_USER_BASE": "ou=users,dc=example,dc=com",
            },
            default_cli_env=True,
            disable_extractors=True,
        )

        assert result.returncode == 0, result.stderr or result.stdout
        assert "LDAP_BACKENDS=archivebox.ldap.auth.ArchiveBoxLDAPBackend," in result.stdout
        assert "LDAP_SERVER_URI=ldap://ldap-test.localhost:389" in result.stdout


class TestLDAPAuthBackend:
    """Test custom LDAP authentication backend."""

    def test_ldap_backend_class_exists(self):
        """Test that ArchiveBoxLDAPBackend class is defined."""
        from archivebox.ldap.auth import ArchiveBoxLDAPBackend

        assert ArchiveBoxLDAPBackend.authenticate_ldap_user is not None

    def test_ldap_backend_inherits_correctly(self):
        """Test that ArchiveBoxLDAPBackend has correct inheritance."""
        from archivebox.ldap.auth import ArchiveBoxLDAPBackend

        # Should have authenticate_ldap_user method (from base or overridden)
        assert callable(ArchiveBoxLDAPBackend.authenticate_ldap_user)


class TestArchiveBoxWithLDAP:
    """Test ArchiveBox commands with LDAP configuration."""

    def test_archivebox_init_without_ldap(self, tmp_path):
        """Test that archivebox init works without LDAP enabled."""
        _cmd_result = run_archivebox_cmd(
            ["init"],
            cwd=tmp_path,
            timeout=45,
            env={"LDAP_ENABLED": "False"},
            default_cli_env=True,
            disable_extractors=True,
        )
        _, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        # Should succeed
        assert code == 0, f"archivebox init failed: {stderr}"

    def test_archivebox_version_with_ldap_config(self, tmp_path):
        """Test that archivebox version works with LDAP config set."""
        _cmd_result = run_archivebox_cmd(
            ["version"],
            cwd=tmp_path,
            timeout=10,
            env={
                "LDAP_ENABLED": "False",
                "LDAP_SERVER_URI": "ldap://ldap-test.localhost:389",
            },
            default_cli_env=True,
            disable_extractors=True,
        )
        _, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        # Should succeed
        assert code == 0, f"archivebox version failed: {stderr}"


class TestLDAPConfigValidationInArchiveBox:
    """Test LDAP config validation when running ArchiveBox commands."""

    def test_archivebox_init_with_incomplete_ldap_config(self, tmp_path):
        """Test that archivebox init fails with helpful error when LDAP config is incomplete."""
        _cmd_result = run_archivebox_cmd(
            ["init"],
            cwd=tmp_path,
            timeout=45,
            env={
                "LDAP_ENABLED": "True",
                # Missing: LDAP_SERVER_URI, LDAP_BIND_DN, etc.
            },
            default_cli_env=True,
            disable_extractors=True,
        )
        _, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        # Should fail with validation error
        assert code != 0, "Should fail with incomplete LDAP config"

        # Check error message
        assert "LDAP_* config options must all be set" in stderr, f"Expected validation error message in: {stderr}"
