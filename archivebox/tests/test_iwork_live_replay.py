# ci-workers: 1
"""Exercise the real Keynote PDF export and replay in its own CI job."""

from .test_provider_plugin_replay import capture_and_replay


def test_public_iwork_capture_and_replay(initialized_archive, browser_runtime):
    capture_and_replay("iwork", initialized_archive, browser_runtime)
