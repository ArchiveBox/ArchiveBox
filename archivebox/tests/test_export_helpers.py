"""Inspect export action descriptors in real server-rendered HTML."""

from lxml.html import fromstring


def export_action_urls(markup):
    actions = fromstring(markup).xpath("//a[@data-export-format]")
    assert actions
    assert all(action.get("href") is None for action in actions)
    return [
        (
            action.get("data-export-route").replace(
                "{format}",
                "rss" if action.get("data-export-format") == "rss_public" else action.get("data-export-format"),
            )
            + ("?" + action.get("data-export-query") if action.get("data-export-query") else ""),
            action.get("data-export-format"),
        )
        for action in actions
    ]
