"""Run plugin-owned host integration cases in the ArchiveBox CI matrix."""

from abx_plugins.plugins.opencode.archivebox.browser_2_cases import (
    pytestmark as pytestmark,
    test_agent_websocket_matches_http_security_policy as test_agent_websocket_matches_http_security_policy,
)
