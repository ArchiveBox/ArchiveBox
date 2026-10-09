"""
Tests for community documentation links in docs/Web-Archiving-Community.md.

These are real-file tests: they read the shipped documentation and verify that
stale or broken project references are removed/updated, without any mocking.
"""

from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
COMMUNITY_DOCS = DOCS_DIR / "Web-Archiving-Community.md"


@pytest.fixture(scope="session")
def community_docs_text() -> str:
    assert COMMUNITY_DOCS.is_file(), f"missing {COMMUNITY_DOCS}"
    return COMMUNITY_DOCS.read_text(encoding="utf-8")


def test_community_docs_has_no_stale_getpolarized_refs(community_docs_text: str) -> None:
    # See issue #1668: getpolarized.io became a Thai gambling site and its
    # references should be removed from the community docs.
    normalized = community_docs_text.lower()
    assert "getpolarized" not in normalized, (
        "docs/Web-Archiving-Community.md still references getpolarized.io "
        "(see https://github.com/ArchiveBox/ArchiveBox/issues/1668)"
    )


def test_community_docs_alternatives_section_still_lists_core_projects(community_docs_text: str) -> None:
    # Guard against over-removal: the "Other ArchiveBox Alternatives" section
    # should still exist and mention well-known, still-active alternatives.
    assert "Other ArchiveBox Alternatives" in community_docs_text
    for expected in ("Browsertrix", "SingleFile", "LinkWarden", "Shaarchiver"):
        assert expected in community_docs_text, f"expected {expected} to remain in community docs"
