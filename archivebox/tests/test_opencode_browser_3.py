"""Run plugin-owned host integration cases in the ArchiveBox CI matrix."""

from abx_plugins.plugins.opencode.archivebox.browser_3_cases import (
    pytestmark as pytestmark,
    test_agent_websocket_rejects_unauthorized_access as test_agent_websocket_rejects_unauthorized_access,
    test_agent_preserves_projects_and_survives_storage_failure as test_agent_preserves_projects_and_survives_storage_failure,
)
