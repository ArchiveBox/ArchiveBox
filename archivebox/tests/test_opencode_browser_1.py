"""Run plugin-owned host integration cases in the ArchiveBox CI matrix."""

from abx_plugins.plugins.opencode.archivebox.browser_1_cases import (
    pytestmark as pytestmark,
    test_agent_navigation_stays_inside_mount as test_agent_navigation_stays_inside_mount,
)
