"""Stable tag badge colors for rendered and exported pages."""


def tag_color_style(name: str) -> str:
    # Keep the trim, lowercase and Unicode-code-point hash in sync with
    # tag-colors.js, which also colors unsaved tags in the browser.
    hue = 0
    for char in (name or "").strip().lower():
        hue = (hue * 31 + ord(char)) % 360
    return f"--tag-bg: hsl({hue}, 70%, 92%); --tag-border: hsl({hue}, 60%, 82%); --tag-fg: hsl({hue}, 35%, 28%);"
