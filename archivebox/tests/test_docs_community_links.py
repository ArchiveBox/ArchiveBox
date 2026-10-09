"""
Tests for community documentation links in docs/Web-Archiving-Community.md.

These are real-file tests: they read the shipped documentation and verify that
project references are correct and any known discrepancies are documented,
without any mocking.
"""

from pathlib import Path

import pytest

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
COMMUNITY_DOCS = DOCS_DIR / "Web-Archiving-Community.md"


@pytest.fixture(scope="session")
def community_docs_text() -> str:
    assert COMMUNITY_DOCS.is_file(), f"missing {COMMUNITY_DOCS}"
    return COMMUNITY_DOCS.read_text(encoding="utf-8")


def test_community_docs_polarized_entry_is_documented(community_docs_text: str) -> None:
    # See issue #1668: the live getpolarized.io domain has been repurposed
    # (Thai gambling site), but the entry links to a valid archived Wayback
    # copy. The maintainer's call was to keep the entry and document the
    # discrepancy rather than delete it.
    normalized = community_docs_text.lower()

    # The Polarized entry should still be present, linking to the Wayback copy.
    assert "polarized" in normalized, "expected Polarized entry to remain in community docs"
    assert "web.archive.org" in normalized and "getpolarized.io" in normalized, (
        "expected the Polarized entry to link to the archived Wayback copy of getpolarized.io"
    )

    # The discrepancy (live domain repurposed) must be documented next to it.
    # Find the Polarized bullet and check the note is on the same line.
    for line in community_docs_text.splitlines():
        if "Polarized" in line and "getpolarized.io" in line:
            assert "repurposed" in line.lower(), (
                "Polarized entry references getpolarized.io but does not document that the live domain has been repurposed (see #1668)"
            )
            return
    pytest.fail("no Polarized line referencing getpolarized.io found in community docs")


def test_community_docs_alternatives_section_still_lists_core_projects(community_docs_text: str) -> None:
    # Guard against over-removal: the "Other ArchiveBox Alternatives" section
    # should still exist and mention well-known, still-active alternatives.
    assert "Other ArchiveBox Alternatives" in community_docs_text
    for expected in ("Browsertrix", "SingleFile", "LinkWarden", "Shaarchiver"):
        assert expected in community_docs_text, f"expected {expected} to remain in community docs"
