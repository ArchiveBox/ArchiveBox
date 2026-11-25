"""Stable tag badge colors for rendered and exported pages."""

import json
import re
from functools import cache
from pathlib import Path


@cache
def _semantic_hues() -> dict[str, int]:
    # The same static dictionary colors both saved and browser-created tags.
    asset = Path(__file__).resolve().parents[1] / "templates/static/tag-color-hues.js"
    return json.loads(asset.read_text(encoding="utf-8").split("const archiveBoxTagColorHues = ", 1)[1].rstrip().removesuffix(";"))


def _hash_hue(text: str) -> int:
    hue = 0
    for char in text:
        hue = (hue * 31 + ord(char)) % 360
    return hue


def tag_color_style(name: str) -> str:
    # Keep the trim, lowercase and Unicode-code-point hash in sync with
    # tag-colors.js, which also colors unsaved tags in the browser.
    normalized = (name or "").strip().lower()
    hue = _hash_hue(normalized)
    hues = _semantic_hues()
    topics = {hues[word] for word in re.findall(r"[^\W_]+", normalized) if word in hues}
    if len(topics) == 1:
        hue = (topics.pop() + hue % 17 - 8) % 360
    elif not topics and (namespace := re.match(r"^([a-z]{3,})[-_:][a-z]{2}", normalized)):
        # For names the dictionary does not know, keep label families together.
        hue = (_hash_hue(namespace[1]) + hue % 17 - 8) % 360
    return f"--tag-bg: hsl({hue}, 70%, 92%); --tag-border: hsl({hue}, 60%, 82%); --tag-fg: hsl({hue}, 35%, 28%);"
