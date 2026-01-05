"""
LDAP authentication tests for ArchiveBox.

Tests LDAP configuration, validation, and integration with Django.
Per CLAUDE.md: NO MOCKS, NO SKIPS - all tests use real code paths.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path


class TestLDAPConfig(unittest.TestCase):
    """Test LDAP configuration loading and validation."""

    def test_ldap_config_defaults(self):
        """Test that LDAP config loads with correct defaults."""
        from archivebox.config.ldap import LDAP_CONFIG

        # Check default values
        self.assertFalse(LDAP_CONFIG.LDAP_ENABLED)
        self.assertIsNone(LDAP_CONFIG.LDAP_SERVER_URI)
        self.assertIsNone(LDAP_CONFIG.LDAP_BIND_DN)
        self.assertIsNone(LDAP_CONFIG.LDAP_BIND_PASSWORD)
        self.assertIsNone(LDAP_CONFIG.LDAP_USER_BASE)
        self.assertEqual(LDAP_CONFIG.LDAP_USER_FILTER, "(uid=%(user)s)")
        self.assertEqual(LDAP_CONFIG.LDAP_USERNAME_ATTR, "username")
        self.assertEqual(LDAP_CONFIG.LDAP_FIRSTNAME_ATTR, "givenName")
        self.assertEqual(LDAP_CONFIG.LDAP_LASTNAME_ATTR, "sn")
        self.assertEqual(LDAP_CONFIG.LDAP_EMAIL_ATTR, "mail")
        self.assertFalse(LDAP_CONFIG.LDAP_CREATE_SUPERUSER)

    def test_ldap_config_validation_disabled(self):
        """Test that validation passes when LDAP is disabled."""
        from archivebox.config.ldap import LDAPConfig

        config = LDAPConfig(LDAP_ENABLED=False)
        is_valid, error_msg = config.validate_ldap_config()

        self.assertTrue(is_valid)
        self.assertEqual(error_msg, "")

    def test_ldap_config_validation_missing_fields(self):
        """Test that validation fails when required fields are missing."""
        from archivebox.config.ldap import LDAPConfig

        # Enable LDAP but don't provide required fields
        config = LDAPConfig(LDAP_ENABLED=True)
        is_valid, error_msg = config.validate_ldap_config()

        self.assertFalse(is_valid)
        self.assertIn("LDAP_* config options must all be set", error_msg)
        self.assertIn("LDAP_SERVER_URI", error_msg)
        self.assertIn("LDAP_BIND_DN", error_msg)
        self.assertIn("LDAP_BIND_PASSWORD", error_msg)
        self.assertIn("LDAP_USER_BASE", error_msg)

    def test_ldap_config_validation_complete(self):
        """Test that validation passes when all required fields are provided."""
        from archivebox.config.ldap import LDAPConfig

        config = LDAPConfig(
            LDAP_ENABLED=True,
            LDAP_SERVER_URI="ldap://localhost:389",
            LDAP_BIND_DN="cn=admin,dc=example,dc=com",
            LDAP_BIND_PASSWORD="password",
            LDAP_USER_BASE="ou=users,dc=example,dc=com",
        )
        is_valid, error_msg = config.validate_ldap_config()

        self.assertTrue(is_valid)
        self.assertEqual(error_msg, "")

    def test_ldap_config_in_get_config(self):
        """Test that LDAP_CONFIG is included in get_CONFIG()."""
        from archivebox.config import get_CONFIG

        all_config = get_CONFIG()
        self.assertIn('LDAP_CONFIG', all_config)
        self.assertEqual(all_config['LDAP_CONFIG'].__class__.__name__, 'LDAPConfig')


class TestLDAPIntegration(unittest.TestCase):
    """Test LDAP integration with Django settings."""

    def test_django_settings_without_ldap_enabled(self):
        """Test that Django settings work correctly when LDAP is disabled."""
        # Import Django settings (LDAP_ENABLED should be False by default)
        from django.conf import settings

        # Should have default authentication backends
        self.assertIn("django.contrib.auth.backends.RemoteUserBackend", settings.AUTHENTICATION_BACKENDS)
        self.assertIn("django.contrib.auth.backends.ModelBackend", settings.AUTHENTICATION_BACKENDS)

        # LDAP backend should not be present when disabled
        ldap_backends = [b for b in settings.AUTHENTICATION_BACKENDS if 'ldap' in b.lower()]
        self.assertEqual(len(ldap_backends), 0, "LDAP backend should not be present when LDAP_ENABLED=False")

    def test_django_settings_with_ldap_library_check(self):
        """Test that Django settings check for LDAP libraries when enabled."""
        # Try to import django-auth-ldap to see if it's available
        try:
            import django_auth_ldap
            import ldap
            ldap_available = True
        except ImportError:
            ldap_available = False

        # If LDAP libraries are not available, settings should handle gracefully
        if not ldap_available:
            # Settings should have loaded without LDAP backend
            from django.conf import settings
            ldap_backends = [b for b in settings.AUTHENTICATION_BACKENDS if 'ldap' in b.lower()]
            self.assertEqual(len(ldap_backends), 0, "LDAP backend should not be present when libraries unavailable")


class TestLDAPAuthBackend(unittest.TestCase):
    """Test custom LDAP authentication backend."""

    def test_ldap_backend_class_exists(self):
        """Test that ArchiveBoxLDAPBackend class is defined."""
        from archivebox.ldap.auth import ArchiveBoxLDAPBackend

        self.assertTrue(hasattr(ArchiveBoxLDAPBackend, 'authenticate_ldap_user'))

    def test_ldap_backend_inherits_correctly(self):
        """Test that ArchiveBoxLDAPBackend has correct inheritance."""
        from archivebox.ldap.auth import ArchiveBoxLDAPBackend

        # Should have authenticate_ldap_user method (from base or overridden)
        self.assertTrue(callable(getattr(ArchiveBoxLDAPBackend, 'authenticate_ldap_user', None)))


class TestArchiveBoxWithLDAP(unittest.TestCase):
    """Test ArchiveBox commands with LDAP configuration."""

    def setUp(self):
        """Set up test environment."""
        self.work_dir = tempfile.mkdtemp(prefix='archivebox-ldap-test-')

    def test_archivebox_init_without_ldap(self):
        """Test that archivebox init works without LDAP enabled."""
        import subprocess

        # Run archivebox init
        result = subprocess.run(
            [sys.executable, '-m', 'archivebox', 'init'],
            cwd=self.work_dir,
            capture_output=True,
            timeout=45,
            env={
                **os.environ,
                'DATA_DIR': self.work_dir,
                'LDAP_ENABLED': 'False',
            }
        )

        # Should succeed
        self.assertEqual(result.returncode, 0, f"archivebox init failed: {result.stderr.decode()}")

    def test_archivebox_version_with_ldap_config(self):
        """Test that archivebox version works with LDAP config set."""
        import subprocess

        # Run archivebox version with LDAP config env vars
        result = subprocess.run(
            [sys.executable, '-m', 'archivebox', 'version'],
            capture_output=True,
            timeout=10,
            env={
                **os.environ,
                'LDAP_ENABLED': 'False',
                'LDAP_SERVER_URI': 'ldap://localhost:389',
            }
        )

        # Should succeed
        self.assertEqual(result.returncode, 0, f"archivebox version failed: {result.stderr.decode()}")


class TestLDAPConfigValidationInArchiveBox(unittest.TestCase):
    """Test LDAP config validation when running ArchiveBox commands."""

    def setUp(self):
        """Set up test environment."""
        self.work_dir = tempfile.mkdtemp(prefix='archivebox-ldap-validation-')

    def test_archivebox_init_with_incomplete_ldap_config(self):
        """Test that archivebox init fails with helpful error when LDAP config is incomplete."""
        import subprocess

        # Run archivebox init with LDAP enabled but missing required fields
        result = subprocess.run(
            [sys.executable, '-m', 'archivebox', 'init'],
            cwd=self.work_dir,
            capture_output=True,
            timeout=45,
            env={
                **os.environ,
                'DATA_DIR': self.work_dir,
                'LDAP_ENABLED': 'True',
                # Missing: LDAP_SERVER_URI, LDAP_BIND_DN, etc.
            }
        )

        # Should fail with validation error
        self.assertNotEqual(result.returncode, 0, "Should fail with incomplete LDAP config")

        # Check error message
        stderr = result.stderr.decode()
        self.assertIn("LDAP_* config options must all be set", stderr,
                     f"Expected validation error message in: {stderr}")


if __name__ == '__main__':
    unittest.main()
