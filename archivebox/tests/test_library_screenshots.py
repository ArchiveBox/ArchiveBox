"""Gallery billing exceptions preserve failed captures and reject other errors."""

import pytest

from archivebox.core.models import ArchiveResult


@pytest.mark.django_db
@pytest.mark.parametrize(
    "message",
    [
        "OpenCode analysis failed: APIError: You have no credits remaining. Add credits to continue using the API at https://platform.openai.com/",
        "OpenCode analysis failed: APIError: Your credit balance is too low to access the Anthropic API",
    ],
)
def test_gallery_warns_for_exhausted_credit_results(snapshot, capsys, message):
    from archivebox.core.library_screenshots import validate_ai_result

    tags_before = list(snapshot.tags.values_list("pk", flat=True))
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="autotag", status="failed", output_str=message)
    assert validate_ai_result(snapshot, "autotag") is False
    assert "::warning::API credits exhausted" in capsys.readouterr().out
    result.refresh_from_db()
    assert result.status == "failed" and result.output_str == message
    assert list(snapshot.tags.values_list("pk", flat=True)) == tags_before


@pytest.mark.django_db
@pytest.mark.parametrize("message", ["OpenCode exited with status 1:", "Invalid API key", "Malformed provider output"])
def test_gallery_keeps_other_ai_failures_fatal(snapshot, message):
    from archivebox.core.library_screenshots import validate_ai_result

    ArchiveResult.objects.create(snapshot=snapshot, plugin="autotag", status="failed", output_str=message)
    with pytest.raises(RuntimeError, match="no successful autotag result"):
        validate_ai_result(snapshot, "autotag")


@pytest.mark.django_db
def test_gallery_requires_result_and_accepts_success(snapshot, capsys):
    from archivebox.core.library_screenshots import validate_ai_result

    with pytest.raises(RuntimeError, match="no successful autotag result"):
        validate_ai_result(snapshot, "autotag")
    ArchiveResult.objects.create(snapshot=snapshot, plugin="autotag", status="succeeded", output_str="autotag/tags.jsonl")
    assert validate_ai_result(snapshot, "autotag") is True
    assert not capsys.readouterr().out
