__package__ = "archivebox.misc"

# Bootable logging primitives (Rich console, ANSI colors, stdout/stderr helpers).
# MUST NOT import archivebox.config, archivebox.core, or Django — this module is
# loaded via config/constants.py during pre-bootstrap, before settings or apps
# are ready. Post-bootstrap CLI logging helpers live in logging_util.py.

import sys
from collections import defaultdict
from random import randint

from rich.console import Console
from rich.highlighter import Highlighter

# SETUP RICH CONSOLE / TTY detection / COLOR / PROGRESS BARS
# Disable wrapping - use soft_wrap=True and large width so text flows naturally
# Colors are preserved, just no hard line breaks inserted
CONSOLE = Console(width=32768, soft_wrap=True, force_terminal=True)
STDERR = Console(stderr=True, width=32768, soft_wrap=True, force_terminal=True)
IS_TTY = sys.stdout.isatty()


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.update(*args, **kwargs)

    @classmethod
    def _wrap(cls, value):
        if isinstance(value, dict) and not isinstance(value, AttrDict):
            return cls(value)
        if isinstance(value, list):
            return [cls._wrap(item) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._wrap(item) for item in value)
        return value

    def __setitem__(self, key, value):
        super().__setitem__(key, self._wrap(value))

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as err:
            raise AttributeError(key) from err


class RainbowHighlighter(Highlighter):
    def highlight(self, text):
        for index in range(len(text)):
            text.stylize(f"color({randint(90, 98)})", index, index + 1)


rainbow = RainbowHighlighter()


DEFAULT_CLI_COLORS = AttrDict(
    {
        "reset": "\033[00;00m",
        "lightblue": "\033[01;30m",
        "lightyellow": "\033[01;33m",
        "lightred": "\033[01;35m",
        "red": "\033[01;31m",
        "green": "\033[01;32m",
        "blue": "\033[01;34m",
        "white": "\033[01;37m",
        "black": "\033[01;30m",
    },
)
ANSI = AttrDict({k: "" for k in DEFAULT_CLI_COLORS.keys()})

COLOR_DICT = defaultdict(
    lambda: [(0, 0, 0), (0, 0, 0)],
    {
        "00": [(0, 0, 0), (0, 0, 0)],
        "30": [(0, 0, 0), (0, 0, 0)],
        "31": [(255, 0, 0), (128, 0, 0)],
        "32": [(0, 200, 0), (0, 128, 0)],
        "33": [(255, 255, 0), (128, 128, 0)],
        "34": [(0, 0, 255), (0, 0, 128)],
        "35": [(255, 0, 255), (128, 0, 128)],
        "36": [(0, 255, 255), (0, 128, 128)],
        "37": [(255, 255, 255), (255, 255, 255)],
    },
)


# Logging Helpers (DEPRECATED, use rich.print instead going forward)
def stdout(*args, color: str | None = None, prefix: str = "", config: dict | None = None) -> None:
    ansi = DEFAULT_CLI_COLORS if (config or {}).get("USE_COLOR") else ANSI

    if color:
        strs = [ansi[color], " ".join(str(a) for a in args), ansi["reset"], "\n"]
    else:
        strs = [" ".join(str(a) for a in args), "\n"]

    sys.stdout.write(prefix + "".join(strs))


def stderr(*args, color: str | None = None, prefix: str = "", config: dict | None = None) -> None:
    ansi = DEFAULT_CLI_COLORS if (config or {}).get("USE_COLOR") else ANSI

    if color:
        strs = [ansi[color], " ".join(str(a) for a in args), ansi["reset"], "\n"]
    else:
        strs = [" ".join(str(a) for a in args), "\n"]

    sys.stderr.write(prefix + "".join(strs))


def hint(text: tuple[str, ...] | list[str] | str, prefix="    ", config: dict | None = None) -> None:
    ansi = DEFAULT_CLI_COLORS if (config or {}).get("USE_COLOR") else ANSI

    if isinstance(text, str):
        stderr(f"{prefix}{ansi['lightred']}Hint:{ansi['reset']} {text}")
    else:
        stderr(f"{prefix}{ansi['lightred']}Hint:{ansi['reset']} {text[0]}")
        for line in text[1:]:
            stderr(f"{prefix}      {line}")
