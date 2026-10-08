# ci-environment: provider-capture
"""Explicit live replay acceptance requiring an authorized browser persona.

Run this file by path with AUTH_STORAGE_FILE set to the existing persona's
storage-state JSON. These tests capture real public documents through the CLI;
the providers require an authenticated browser for their native export menus.
"""

import os
from pathlib import Path

import pytest

from .test_provider_plugin_replay import capture_and_replay


@pytest.mark.parametrize("plugin", ["figma", "miro", "canva"])
def test_authenticated_public_provider_capture_and_replay(plugin, initialized_archive, browser_runtime):
    auth = os.environ.get("AUTH_STORAGE_FILE")
    assert auth and Path(auth).is_file(), "Set AUTH_STORAGE_FILE to an authorized provider persona"
    # Match the signed-in interactive browser used by these provider export
    # flows. Figma and Canva reject headless Chromium even with valid cookies.
    capture_and_replay(plugin, initialized_archive, browser_runtime, headless=False)
