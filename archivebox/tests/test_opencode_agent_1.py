"""Run plugin-owned host integration cases in the ArchiveBox CI matrix."""

from abx_plugins.plugins.opencode.archivebox.agent_1_cases import (
    pytestmark as pytestmark,
    test_opencode_disabled_via_cli_stays_disabled as test_opencode_disabled_via_cli_stays_disabled,
    test_opencode_proxy_blocks_cross_site_fetch_metadata as test_opencode_proxy_blocks_cross_site_fetch_metadata,
    test_opencode_proxy_waits_for_owned_process_readiness as test_opencode_proxy_waits_for_owned_process_readiness,
    test_opencode_proxy_preserves_protocol_headers as test_opencode_proxy_preserves_protocol_headers,
    test_opencode_starts_with_isolated_state as test_opencode_starts_with_isolated_state,
    test_opencode_incomplete_install_does_not_break_archivebox as test_opencode_incomplete_install_does_not_break_archivebox,
)
