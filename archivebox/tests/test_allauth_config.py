import json
import os
import subprocess
import sys

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


def test_allauth_disabled_does_not_activate_django(tmp_path):
    env = os.environ.copy()
    env["ALLAUTH_ENABLED"] = "false"
    env["DATA_DIR"] = str(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import django
import json

django.setup()

from django.conf import settings
from django.urls import Resolver404, resolve

try:
    resolve('/accounts/login/')
    accounts_route_enabled = True
except Resolver404:
    accounts_route_enabled = False

print(json.dumps({
    'app_enabled': 'allauth.account' in settings.INSTALLED_APPS,
    'backend_enabled': 'allauth.account.auth_backends.AuthenticationBackend' in settings.AUTHENTICATION_BACKENDS,
    'route_enabled': accounts_route_enabled,
}))
""",
        ],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    state = json.loads(result.stdout.splitlines()[-1])
    assert state == {"app_enabled": False, "backend_enabled": False, "route_enabled": False}


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
