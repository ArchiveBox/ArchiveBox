# ci-environment: live-provider
"""Monitor the external iCloud fixture independently of release CI."""

from .test_provider_plugin_replay import capture_and_replay


def test_public_iwork_capture_and_replay(initialized_archive, browser_runtime):
    # Preserve the original anonymous test's headed/headless behavior and assertions.
    capture_and_replay("iwork", initialized_archive, browser_runtime)
