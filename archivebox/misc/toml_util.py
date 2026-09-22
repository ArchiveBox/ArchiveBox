from typing import Any, cast
from collections.abc import Callable

import json
import toml
import re

from pathlib import Path, PosixPath


def better_toml_dump_str(val: Any) -> str:
    try:
        dump_str = cast(Callable[[Any], str], toml.encoder._dump_str)
        return dump_str(val)
    except Exception:
        # if we hit any of toml's numerous encoding bugs,
        # fall back to using json representation of string
        return json.dumps(str(val))


class CustomTOMLEncoder(toml.encoder.TomlEncoder):
    """
    Custom TomlEncoder to work around https://github.com/uiri/toml's many encoding bugs.
    >>> toml.dumps(value, encoder=CustomTOMLEncoder())
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        dump_funcs = cast(dict[Any, Callable[[Any], str]], self.dump_funcs)
        dump_funcs[Path] = lambda x: json.dumps(str(x))
        dump_funcs[PosixPath] = lambda x: json.dumps(str(x))
        dump_funcs[str] = better_toml_dump_str
        dump_funcs[re.RegexFlag] = better_toml_dump_str
