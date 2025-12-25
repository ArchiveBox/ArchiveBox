__package__ = 'archivebox.misc'

# Low-level logging primitives (Rich console, ANSI colors, stdout/stderr helpers)
# Higher-level logging functions are in logging_util.py

import sys
from typing import Optional, Union, Tuple, List
from collections import defaultdict
from random import randint

from benedict import benedict
from rich.console import Console
from rich.highlighter import Highlighter

# SETUP RICH CONSOLE / TTY detection / COLOR / PROGRESS BARS
# Disable wrapping - use soft_wrap=True and large width so text flows naturally
# Colors are preserved, just no hard line breaks inserted
CONSOLE = Console(width=32768, soft_wrap=True, force_terminal=True)
STDERR = Console(stderr=True, width=32768, soft_wrap=True, force_terminal=True)
IS_TTY = sys.stdout.isatty()

class RainbowHighlighter(Highlighter):
    def highlight(self, text):
        for index in range(len(text)):
            text.stylize(f"color({randint(90, 98)})", index, index + 1)

rainbow = RainbowHighlighter()


DEFAULT_CLI_COLORS = benedict(
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
    }
)
ANSI = benedict({k: '' for k in DEFAULT_CLI_COLORS.keys()})

COLOR_DICT = defaultdict(lambda: [(0, 0, 0), (0, 0, 0)], {
    '00': [(0, 0, 0), (0, 0, 0)],
    '30': [(0, 0, 0), (0, 0, 0)],
    '31': [(255, 0, 0), (128, 0, 0)],
    '32': [(0, 200, 0), (0, 128, 0)],
    '33': [(255, 255, 0), (128, 128, 0)],
    '34': [(0, 0, 255), (0, 0, 128)],
    '35': [(255, 0, 255), (128, 0, 128)],
    '36': [(0, 255, 255), (0, 128, 128)],
    '37': [(255, 255, 255), (255, 255, 255)],
})

# Logging Helpers (DEPRECATED, use rich.print instead going forward)
def stdout(*args, color: Optional[str]=None, prefix: str='', config: Optional[benedict]=None) -> None:
    ansi = DEFAULT_CLI_COLORS if (config or {}).get('USE_COLOR') else ANSI

    if color:
        strs = [ansi[color], ' '.join(str(a) for a in args), ansi['reset'], '\n']
    else:
        strs = [' '.join(str(a) for a in args), '\n']

    sys.stdout.write(prefix + ''.join(strs))

def stderr(*args, color: Optional[str]=None, prefix: str='', config: Optional[benedict]=None) -> None:
    ansi = DEFAULT_CLI_COLORS if (config or {}).get('USE_COLOR') else ANSI

    if color:
        strs = [ansi[color], ' '.join(str(a) for a in args), ansi['reset'], '\n']
    else:
        strs = [' '.join(str(a) for a in args), '\n']

    sys.stderr.write(prefix + ''.join(strs))

def hint(text: Union[Tuple[str, ...], List[str], str], prefix='    ', config: Optional[benedict]=None) -> None:
    ansi = DEFAULT_CLI_COLORS if (config or {}).get('USE_COLOR') else ANSI

    if isinstance(text, str):
        stderr('{}{lightred}Hint:{reset} {}'.format(prefix, text, **ansi))
    else:
        stderr('{}{lightred}Hint:{reset} {}'.format(prefix, text[0], **ansi))
        for line in text[1:]:
            stderr('{}      {}'.format(prefix, line))
