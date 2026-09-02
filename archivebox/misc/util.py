__package__ = "archivebox.misc"

# Bootable utility functions (URL parsing, date parsing, JSON encoding, decorators).
# MUST NOT import archivebox.config, archivebox.core, or Django — this module is
# loaded by hooks.py and other early code paths. Only depends on stdlib and the
# bootable .logging module.

import re
import json as pyjson
import http.cookiejar
from decimal import Decimal, InvalidOperation

from typing import Any
from collections.abc import Callable
from pathlib import Path
from inspect import signature
from functools import wraps
from urllib.parse import urlparse, quote, unquote
from html import escape, unescape
from datetime import datetime, timezone

from .logging import COLOR_DICT


def filter_queryset_by_uuid_substring(queryset, slug: str, field: str = "id"):
    """Filter a queryset to UUID-column matches by prefix or suffix (case-insensitive).

    Avoids ``id__icontains`` (an unindexed full-table scan over the UUID column) by
    stripping non-hex chars from ``slug`` and matching with ``istartswith`` /
    ``iendswith``. Returns an empty queryset for inputs with fewer than 8 hex chars
    to avoid overly broad matches. A full 32-char hex string falls back to an
    exact-equality lookup.
    """
    from django.db.models import Q

    normalized = re.sub(r"[^0-9a-fA-F]", "", slug or "").lower()
    if len(normalized) < 8:
        return queryset.none()
    if len(normalized) == 32:
        return queryset.filter(**{field: normalized})
    prefix = f"{field}__istartswith"
    suffix = f"{field}__iendswith"
    return queryset.filter(Q(**{prefix: normalized}) | Q(**{suffix: normalized}))


### Parsing Helpers

# All of these are (str) -> str
# shortcuts to: https://docs.python.org/3/library/urllib.parse.html#url-parsing
scheme = lambda url: urlparse(url).scheme.lower()
without_scheme = lambda url: urlparse(url)._replace(scheme="").geturl().strip("//")
without_query = lambda url: urlparse(url)._replace(query="").geturl().strip("//")
without_fragment = lambda url: urlparse(url)._replace(fragment="").geturl().strip("//")
without_path = lambda url: urlparse(url)._replace(path="", fragment="", query="").geturl().strip("//")
path = lambda url: urlparse(url).path
basename = lambda url: urlparse(url).path.rsplit("/", 1)[-1]
domain = lambda url: urlparse(url).netloc
query = lambda url: urlparse(url).query
fragment = lambda url: urlparse(url).fragment
extension = lambda url: basename(url).rsplit(".", 1)[-1].lower() if "." in basename(url) else ""
base_url = lambda url: without_scheme(url)  # uniq base url used to dedupe links

urlencode = lambda s: s and quote(s, encoding="utf-8", errors="replace")
urldecode = lambda s: s and unquote(s)
htmlencode = lambda s: s and escape(s, quote=True)
htmldecode = lambda s: s and unescape(s)


def sanitize_html_text(value: Any) -> str:
    """Strip all HTML from user-editable text before storing it."""
    if value is None:
        return ""
    import bleach

    return bleach.clean(
        str(value),
        tags=[],
        attributes={},
        protocols=[],
        strip=True,
        strip_comments=True,
    )


def ts_to_date_str(ts: Any) -> str | None:
    parsed = parse_date(ts)
    return None if parsed is None else parsed.strftime("%Y-%m-%d %H:%M")


COLOR_REGEX = re.compile(r"\[(?P<arg_1>\d+)(;(?P<arg_2>\d+)(;(?P<arg_3>\d+))?)?m")


# https://mathiasbynens.be/demo/url-regex
URL_REGEX = re.compile(
    r"(?=("
    r"http[s]?://"  # start matching from allowed schemes
    r"(?:[a-zA-Z]|[0-9]"  # followed by allowed alphanum characters
    r"|[-_$@.&+!*\(\),]"  #   or allowed symbols (keep hyphen first to match literal hyphen)
    r"|[^\u0000-\u007F])+"  #   or allowed unicode bytes
    r'[^\]\[<>"\'\s]+'  # stop parsing at these symbols
    r"))",
    re.IGNORECASE | re.UNICODE,
)

# Maximum supported URL length. Very long URLs are rare but must be supported correctly
# (e.g. data: URLs, deeply nested query strings). The Snapshot.url column is stored as a
# variable-length TextField (so short URLs don't reserve space and very long URLs still
# fit) while keeping a normal index on the field so exact, prefix, and substring lookups
# all keep working.
MAX_URL_LENGTH = 65535

QUOTE_DELIMITERS = (
    '"',
    "'",
    "`",
    "“",
    "”",
    "‘",
    "’",
)
QUOTE_ENTITY_DELIMITERS = (
    "&quot;",
    "&#34;",
    "&#x22;",
    "&apos;",
    "&#39;",
    "&#x27;",
)
URL_ENTITY_REPLACEMENTS = (
    ("&amp;", "&"),
    ("&#38;", "&"),
    ("&#x26;", "&"),
)

FILESIZE_UNITS: dict[str, int] = {
    "": 1,
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "mib": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "gib": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
    "tib": 1024**4,
}


def sanitize_extracted_url(url: str) -> str:
    """Trim quote garbage and dangling prose punctuation from an extracted URL candidate."""
    cleaned = (url or "").strip()
    if not cleaned:
        return cleaned

    lower_cleaned = cleaned.lower()
    cut_index = len(cleaned)

    for delimiter in QUOTE_DELIMITERS:
        found_index = cleaned.find(delimiter)
        if found_index != -1:
            cut_index = min(cut_index, found_index)

    for delimiter in QUOTE_ENTITY_DELIMITERS:
        found_index = lower_cleaned.find(delimiter)
        if found_index != -1:
            cut_index = min(cut_index, found_index)

    cleaned = cleaned[:cut_index].strip()
    lower_cleaned = cleaned.lower()
    for entity, replacement in URL_ENTITY_REPLACEMENTS:
        while entity in lower_cleaned:
            entity_index = lower_cleaned.find(entity)
            cleaned = cleaned[:entity_index] + replacement + cleaned[entity_index + len(entity) :]
            lower_cleaned = cleaned.lower()

    cleaned = cleaned.rstrip(".,;:!?\\'\"")
    cleaned = cleaned.rstrip('"')

    return cleaned


def validate_url_length(url: str) -> str:
    if len(url) > MAX_URL_LENGTH:
        raise ValueError(f"URL is too long ({len(url)} characters). Maximum length is {MAX_URL_LENGTH} characters.")
    return url


def validate_url(url: str) -> str:
    url = (url or "").strip()
    if "\n" in url or "\r" in url:
        raise ValueError("URL must be a single line.")
    url = validate_url_length(url)
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError("URL must start with http:// or https:// and include a hostname.")
    return url


def parens_are_matched(string: str, open_char="(", close_char=")"):
    """check that all parentheses in a string are balanced and nested properly"""
    count = 0
    for c in string:
        if c == open_char:
            count += 1
        elif c == close_char:
            count -= 1
        if count < 0:
            return False
    return count == 0


def fix_url_from_markdown(url_str: str) -> str:
    """
    cleanup a regex-parsed url that may contain dangling trailing parens from markdown link syntax
    helpful to fix URLs parsed from markdown e.g.
      input:  https://wikipedia.org/en/some_article_(Disambiguation).html?abc=def).somemoretext
      result: https://wikipedia.org/en/some_article_(Disambiguation).html?abc=def

    IMPORTANT ASSUMPTION: valid urls wont have unbalanced or incorrectly nested parentheses
    e.g. this will fail the user actually wants to ingest a url like 'https://example.com/some_wei)(rd_url'
         in that case it will return https://example.com/some_wei (truncated up to the first unbalanced paren)
    This assumption is true 99.9999% of the time, and for the rare edge case the user can use url_list parser.
    """
    trimmed_url = url_str
    if len(trimmed_url) > 2048:
        return trimmed_url

    # cut off one trailing character at a time
    # until parens are balanced e.g. /a(b)c).x(y)z -> /a(b)c
    trim_attempts = 0
    while trimmed_url and not parens_are_matched(trimmed_url) and trim_attempts < 256:
        trimmed_url = trimmed_url[:-1]
        trim_attempts += 1

    if not trimmed_url or not parens_are_matched(trimmed_url):
        return url_str

    # make sure trimmed url is still valid
    if any(match == trimmed_url for match in re.findall(URL_REGEX, trimmed_url)):
        return trimmed_url

    return url_str


def split_comma_separated_urls(url: str):
    offset = 0
    while True:
        http_index = url.find("http://", 1)
        https_index = url.find("https://", 1)
        next_indices = [idx for idx in (http_index, https_index) if idx != -1]
        if not next_indices:
            yield offset, url
            return

        next_index = min(next_indices)
        if url[next_index - 1] != ",":
            yield offset, url
            return

        yield offset, url[: next_index - 1]
        offset += next_index
        url = url[next_index:]


def find_all_urls(urls_str: str):
    skipped_starts = set()
    for match in re.finditer(URL_REGEX, urls_str):
        if match.start() in skipped_starts:
            continue

        cleaned_match = sanitize_extracted_url(fix_url_from_markdown(match.group(1)))
        for offset, url in split_comma_separated_urls(cleaned_match):
            if offset:
                skipped_starts.add(match.start() + offset)
            yield url


def parse_filesize_to_bytes(value: str | int | float | None) -> int:
    """
    Parse a byte count from an integer or human-readable string like 45mb or 2 GB.
    """
    if value is None:
        return 0

    if isinstance(value, bool):
        raise ValueError("Size value must be an integer or size string.")

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("Size value must resolve to a whole number of bytes.")
        return int(value)

    raw_value = str(value).strip()
    if not raw_value:
        return 0

    if raw_value.isdigit():
        return int(raw_value)

    match = re.fullmatch(r"(?i)(\d+(?:\.\d+)?)\s*([a-z]+)", raw_value)
    if not match:
        raise ValueError(f"Invalid size value: {value}")

    amount_str, unit_str = match.groups()
    multiplier = FILESIZE_UNITS.get(unit_str.lower())
    if multiplier is None:
        raise ValueError(f"Unknown size unit: {unit_str}")

    try:
        amount = Decimal(amount_str)
    except InvalidOperation as err:
        raise ValueError(f"Invalid size value: {value}") from err

    return int(amount * multiplier)


def enforce_types(func):
    """
    Enforce function arg and kwarg types at runtime using its python3 type hints
    Simpler version of pydantic @validate_call decorator
    """
    # TODO: check return type as well

    @wraps(func)
    def typechecked_function(*args, **kwargs):
        sig = signature(func)

        def check_argument_type(arg_key, arg_val):
            try:
                annotation = sig.parameters[arg_key].annotation
            except KeyError:
                annotation = None

            if annotation is not None and annotation.__class__ is type:
                if not isinstance(arg_val, annotation):
                    raise TypeError(
                        "{}(..., {}: {}) got unexpected {} argument {}={}".format(
                            func.__name__,
                            arg_key,
                            annotation.__name__,
                            type(arg_val).__name__,
                            arg_key,
                            str(arg_val)[:64],
                        ),
                    )

        # check args
        for arg_val, arg_key in zip(args, sig.parameters):
            check_argument_type(arg_key, arg_val)

        # check kwargs
        for arg_key, arg_val in kwargs.items():
            check_argument_type(arg_key, arg_val)

        return func(*args, **kwargs)

    return typechecked_function


def docstring(text: str | None):
    """attach the given docstring to the decorated function"""

    def decorator(func):
        if text:
            func.__doc__ = text
        return func

    return decorator


@enforce_types
def parse_date(date: Any) -> datetime | None:
    """Parse unix timestamps, iso format, and human-readable strings"""

    if date is None:
        return None

    if isinstance(date, datetime):
        if date.tzinfo is None:
            return date.replace(tzinfo=timezone.utc)

        offset = date.utcoffset()
        assert offset == datetime.now(timezone.utc).utcoffset(), "Refusing to load a non-UTC date!"
        return date

    if isinstance(date, (float, int)):
        date = str(date)

    if isinstance(date, str):
        normalized = date.strip()
        if not normalized:
            raise ValueError(f"Tried to parse invalid date string! {date}")

        try:
            return datetime.fromtimestamp(float(normalized), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass

        try:
            iso_date = normalized.replace("Z", "+00:00")
            parsed_date = datetime.fromisoformat(iso_date)
            if parsed_date.tzinfo is None:
                return parsed_date.replace(tzinfo=timezone.utc)
            return parsed_date.astimezone(timezone.utc)
        except ValueError:
            pass

        from dateparser import parse as dateparser

        parsed_date = dateparser(normalized, settings={"TIMEZONE": "UTC"})
        if parsed_date is None:
            raise ValueError(f"Tried to parse invalid date string! {date}")
        return parsed_date.astimezone(timezone.utc)

    raise ValueError(f"Tried to parse invalid date! {date}")


@enforce_types
def download_url(url: str, timeout: int | None = None, config=None, **config_kwargs) -> str:
    """Download the contents of a remote url and return the text"""

    import requests
    from w3lib.encoding import html_body_declared_encoding, http_content_type_encoding

    from archivebox.config.common import get_config

    config = config or get_config(**config_kwargs)
    timeout = timeout or config.TIMEOUT
    session = requests.Session()

    if config.COOKIES_FILE and Path(config.COOKIES_FILE).is_file():
        cookie_jar = http.cookiejar.MozillaCookieJar(config.COOKIES_FILE)
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
        for cookie in cookie_jar:
            if cookie.value is not None:
                session.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)

    response = session.get(
        url,
        headers={"User-Agent": config.USER_AGENT},
        verify=config.CHECK_SSL_VALIDITY,
        timeout=timeout,
    )

    content_type = response.headers.get("Content-Type", "")
    encoding = http_content_type_encoding(content_type) or html_body_declared_encoding(response.text)

    if encoding is not None:
        response.encoding = encoding

    try:
        return response.text
    except UnicodeDecodeError:
        # if response is non-test (e.g. image or other binary files), just return the filename instead
        return url.rsplit("/", 1)[-1]


@enforce_types
def ansi_to_html(text: str) -> str:
    """
    Based on: https://stackoverflow.com/questions/19212665/python-converting-ansi-color-codes-to-html
    Simple way to render colored CLI stdout/stderr in HTML properly, Textual/rich is probably better though.
    """

    TEMPLATE = '<span style="color: rgb{}"><br>'
    text = text.replace("[m", "</span>")

    def single_sub(match):
        argsdict = match.groupdict()
        if argsdict["arg_3"] is None:
            if argsdict["arg_2"] is None:
                _, color = 0, argsdict["arg_1"]
            else:
                _, color = argsdict["arg_1"], argsdict["arg_2"]
        else:
            _, color = argsdict["arg_3"], argsdict["arg_2"]

        return TEMPLATE.format(COLOR_DICT[color][0])

    return COLOR_REGEX.sub(single_sub, text)


class ExtendedEncoder(pyjson.JSONEncoder):
    """
    Extended json serializer that supports serializing several model
    fields and objects
    """

    def default(self, o):
        cls_name = o.__class__.__name__

        if isinstance(o, tuple) and "_asdict" in vars(type(o)):
            return o._asdict()

        elif isinstance(o, bytes):
            return o.decode()

        elif isinstance(o, datetime):
            return o.isoformat()

        elif isinstance(o, Exception):
            return f"{o.__class__.__name__}: {o}"

        elif isinstance(o, Path):
            return str(o)

        elif cls_name in ("dict_items", "dict_keys", "dict_values"):
            return list(o)

        elif isinstance(o, Callable):
            return str(o)

        # Try dict/list conversion as fallback
        try:
            return dict(o)
        except Exception:
            pass

        try:
            return list(o)
        except Exception:
            pass

        try:
            return str(o)
        except Exception:
            pass

        return pyjson.JSONEncoder.default(self, o)


@enforce_types
def to_json(obj: Any, indent: int | None = 4, sort_keys: bool = True) -> str:
    """Serialize object to JSON string with extended type support"""
    return pyjson.dumps(obj, indent=indent, sort_keys=sort_keys, cls=ExtendedEncoder)
