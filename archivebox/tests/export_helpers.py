"""Read export targets from real server-rendered HTML."""

from lxml.html import fromstring


def export_action_urls(markup, *, public=False):
    actions = fromstring(markup).xpath("//a[@data-export-format]")
    assert actions
    links = []
    for action in actions:
        format = action.get("data-export-format")
        route = action.get("data-export-route").replace("{format}", "rss" if format == "rss_public" else format)
        query = action.get("data-export-query")
        url = f"{route}?{query}" if query else route
        assert action.get("href") == (None if public else url)
        links.append((url, format))
    return links
