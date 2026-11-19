#!/usr/bin/env python3
"""
Tests for archivebox tag command.
"""

import pytest

from archivebox.core.models import Snapshot, Tag
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_tag_help_runs_successfully(tmp_path):
    """The tag command should be registered and expose help."""

    result = run_archivebox_cmd(["tag", "--help"])

    assert result.returncode == 0
    assert "tag" in result.stdout.lower()
    assert "list" in result.stdout


def test_tag_merge_moves_snapshots_and_deletes_merged_tags(tmp_path, initialized_archive):
    """`tag merge` retags snapshots onto the target (created if missing) and removes the merged tags."""
    env = cli_env(disable_extractors=True)
    for url, tag in (("https://example.com/one", "News"), ("https://example.com/two", "news-articles")):
        result = run_archivebox_cmd(
            ["snapshot", "create", "--tag", tag, url],
            cwd=initialized_archive,
            env=env,
        )
        assert result.returncode == 0, result.stderr

    result = run_archivebox_cmd(
        ["tag", "merge", "--into", "headlines", "news", "news-articles"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "Merged 2 tags into headlines (2 snapshots retagged)" in result.stderr
    with use_archivebox_db(tmp_path):
        assert list(Tag.objects.values_list("name", flat=True)) == ["headlines"]
        assert Snapshot.objects.filter(tags__name="headlines").count() == 2


def test_tag_merge_fails_for_unknown_tag(tmp_path, initialized_archive):
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(["tag", "create", "keep"], cwd=initialized_archive, env=env)

    result = run_archivebox_cmd(["tag", "merge", "--into", "keep", "missing"], cwd=initialized_archive, env=env)

    assert result.returncode == 1
    assert "Tag not found: missing" in result.stderr
    with use_archivebox_db(tmp_path):
        assert list(Tag.objects.values_list("name", flat=True)) == ["keep"]
