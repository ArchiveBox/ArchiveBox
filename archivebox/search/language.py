"""Snapshot search expressions shared by web, API, CLI and Smart Folders."""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache, reduce
from operator import and_, or_

from django.db import connections
from django.db.models import BooleanField, Exists, Func, OuterRef, Q, TextField, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast, Coalesce
from django.db.models.lookups import IRegex, Regex

from archivebox.core.models import ArchiveResult, SnapshotQuerySet, SnapshotTag


@dataclass(frozen=True)
class Term:
    field: str
    value: str
    items: tuple = ()


@dataclass(frozen=True)
class Expr:
    op: str
    args: tuple


# Scan at the current offset. In particular, an unclosed literal must fail
# there instead of restarting a search at each escaped quote inside it.
TOKEN = re.compile(r'\s+|[()~]|[^\s()~"]+')
UNQUOTED_ITEM = re.compile(r'[^",\s]+')
JSON_STRING = json.JSONDecoder()
ALIASES = {"tag": "tags", "site": "domain"}
OPERATORS = {
    "tags": ("tag", "Tag name contains this text"),
    "plugins": ("puzzle", "Successful plugin name contains this text"),
    "owner": ("user", "Username contains this text"),
    "domain": ("globe", "Website domain"),
    "after": ("calendar", "Bookmarked on or after a date"),
    "before": ("calendar", "Bookmarked before a date"),
    "bookmarked": ("calendar", "Bookmarked in a year, month or day"),
    "status": ("check", "Snapshot state"),
    "filetype": ("file", "Contains a saved file of this type"),
    "permissions": ("lock", "Snapshot visibility"),
    "title": ("type", "Title contains this text"),
    "meta": ("database", "Search database metadata"),
    "deep": ("file", "Search archived file contents"),
    "linksto": ("out", "Outgoing URL contains this text."),
    "linkedfrom": ("link", "Source URL contains this text."),
}


def parse(source):
    if len(source) > 4096:
        raise ValueError("Query exceeds 4096 characters")
    tokens = []
    end = 0
    while end < len(source):
        start = end
        if source[start] == '"':
            try:
                _, end = JSON_STRING.raw_decode(source, start)
            except ValueError as error:
                raise ValueError(f"Invalid quoted text at {start}") from error
        else:
            end = TOKEN.match(source, start).end()
        token = source[start:end]
        if not token.isspace():
            tokens.append((token, start, end))
    if not tokens or len(tokens) > 128:
        raise ValueError("Empty, incomplete, or overlong query")
    i = 0

    def peek():
        return tokens[i][0] if i < len(tokens) else None

    def primary():
        nonlocal i
        word = peek()
        if word in (None, ")", "AND", "OR"):
            raise ValueError("Expected a search term")
        i += 1
        if word == "~":
            return Expr("not", (primary(),))
        if word == "(":
            node = disjunction()
            if peek() != ")":
                raise ValueError("Expected closing parenthesis")
            i += 1
            return node
        if word.startswith('"'):
            return Term("literal", json.loads(word))
        field, sep, value = word.partition(":")
        if not sep or word.lower().startswith(("https://", "http://")):
            return Term("word", word)
        field = field.lower()
        field = ALIASES.get(field, field)
        if field not in OPERATORS and not re.fullmatch(r"[a-z][a-z0-9_]*__[a-z_]+", field):
            raise ValueError(f"Unknown field {field}")
        if field in ("tags", "plugins", "filetype"):
            # A quoted list item can contain commas, spaces or colons. Split
            # before decoding quotes; splitting the decoded value loses that boundary.
            start = tokens[i - 1][1] + word.index(":") + 1
            while i < len(tokens) and tokens[i][1] == tokens[i - 1][2] and peek() not in ("(", ")", "~"):
                i += 1
            raw = source[start : tokens[i - 1][2]]
            values = []
            cursor = 0
            while cursor < len(raw):
                if raw[cursor] == '"':
                    part, cursor = JSON_STRING.raw_decode(raw, cursor)
                else:
                    item = UNQUOTED_ITEM.match(raw, cursor)
                    if not item:
                        raise ValueError(f"Invalid {field} list")
                    part, cursor = item[0], item.end()
                if not part or len(values) == 100:
                    raise ValueError(f"Use between 1 and 100 nonempty values for {field}")
                values.append(part)
                if cursor == len(raw):
                    break
                if raw[cursor] != "," or cursor + 1 == len(raw):
                    raise ValueError(f"Invalid {field} list")
                cursor += 1
            if not values:
                raise ValueError(f"Invalid {field} list")
            decoded = ",".join(values)
            return Term(
                field,
                decoded,
                tuple(values) if any("," in part for part in values) else (),
            )
        if not value and peek() and peek().startswith('"') and tokens[i][1] == tokens[i - 1][2]:
            value = json.loads(peek())
            i += 1
        if not value:
            raise ValueError(f"Empty {field}")
        return Term(field, value)

    def conjunction():
        nonlocal i
        terms = [primary()]
        while peek() not in (None, ")", "OR"):
            if peek() == "AND":
                i += 1
            terms.append(primary())
        return terms[0] if len(terms) == 1 else Expr("and", tuple(terms))

    def disjunction():
        nonlocal i
        terms = [conjunction()]
        while peek() == "OR":
            i += 1
            terms.append(conjunction())
        return terms[0] if len(terms) == 1 else Expr("or", tuple(terms))

    tree = disjunction()
    if peek() is not None or any(not t.value for t in leaves(tree)):
        raise ValueError("Unexpected token or empty literal")
    if any("\x00" in term.value or re.search(r"[\ud800-\udfff]", term.value) for term in leaves(tree)):
        raise ValueError("Search values must contain valid text")
    return tree


def leaves(node):
    if isinstance(node, Term):
        yield node
    else:
        for arg in node.args:
            yield from leaves(arg)


def simplify(node, values):
    """Keep unverified leaves symbolic so a missing artifact cannot prove NOT."""
    if isinstance(node, Term):
        return values.get(node, node)
    if isinstance(node, bool):
        return node
    args = [simplify(arg, values) for arg in node.args]
    if node.op == "not":
        return not args[0] if isinstance(args[0], bool) else Expr("not", tuple(args))
    decisive = node.op == "or"
    if decisive in args:
        return decisive
    remaining = tuple(dict.fromkeys(a for a in args if not isinstance(a, bool)))
    if not remaining:
        return not decisive
    return remaining[0] if len(remaining) == 1 else Expr(node.op, remaining)


def sql_bounds(node, sql, text=None):
    """Bound membership before file/index I/O. NOT reverses possible and certain."""
    if isinstance(node, Term):
        return (sql[node], sql[node]) if node in sql else ((text or {}).get(node, False), True)
    bounds = [sql_bounds(arg, sql, text) for arg in node.args]
    if node.op == "not":
        return tuple(not q if isinstance(q, bool) else ~q for q in reversed(bounds[0]))
    decisive = node.op == "or"

    def combine(seq):
        if any(v is decisive for v in seq):
            return decisive
        parts = [v for v in seq if isinstance(v, Q)]
        return reduce(or_ if decisive else and_, parts) if parts else not decisive

    return tuple(combine(col) for col in zip(*bounds))


def has_uppercase(value):
    # Each operator decides from its decoded value. Field names, Boolean
    # keywords and neighboring operands never affect the decision.
    return any(char.isupper() for char in value)


@lru_cache(maxsize=128)
def literal_pattern(value):
    return re.compile(re.escape(value), 0 if has_uppercase(value) else re.IGNORECASE)


def substring(field, value, *, match_case=None):
    # SQLite LIKE only folds ASCII. Django's regex lookups support Unicode,
    # and escaping the whole needle keeps punctuation and spaces literal.
    if match_case is None:
        match_case = has_uppercase(value)
    lookup = Regex if match_case else IRegex
    text = Coalesce(field, Value(""), output_field=TextField())
    return Q(lookup(text, Value(re.escape(value))))


class ConfigContains(Func):
    """Django can address a known JSON path; here we need every scalar value."""

    output_field = BooleanField()
    arity = 2

    def __init__(self, field, needle):
        self.match_case = has_uppercase(needle)
        super().__init__(field, Value(re.escape(needle)))

    def as_sql(self, compiler, connection, **extra_context):
        # Let Django qualify the column and bind the needle even inside a joined
        # or aliased subquery. Only the set-returning JSON primitive is vendor SQL.
        column, lhs_params = compiler.compile(self.source_expressions[0])
        value, rhs_params = compiler.compile(self.source_expressions[1])
        if connection.vendor == "postgresql":
            operator = "~" if self.match_case else "~*"
            sql = f"""SELECT 1 FROM jsonb_path_query({column}, 'strict $.**') AS j(val)
                      WHERE jsonb_typeof(j.val) IN ('string','number','boolean')
                        AND (j.val #>> '{{}}') {operator} {value}"""
        else:
            prefix = "" if self.match_case else "(?i)"
            sql = f"""SELECT 1 FROM json_tree({column}) j WHERE j.type NOT IN ('null','array','object')
                      AND (CASE j.type WHEN 'true' THEN 'true' WHEN 'false' THEN 'false'
                                ELSE CAST(j.atom AS TEXT) END) REGEXP ('{prefix}' || {value})"""
        return f"EXISTS ({sql})", (*lhs_params, *rhs_params)


def text_metadata(term, *, public):
    # These are positive witnesses for ordinary or quoted text. An absent
    # metadata match still leaves the configured index free to confirm the row.
    fields = ["title", "url", "timestamp", "crawl__created_by__username"]
    if not public:
        fields.extend(("notes", "crawl__notes", "crawl__label"))
    tags = SnapshotTag.objects.filter(substring("tag__name", term.value)).values("snapshot_id")
    return reduce(or_, (substring(f, term.value) for f in fields)) | Q(pk__in=tags)


def sql_leaf(term, db, *, rules=None, stack=(), public=False):
    f, v = term.field, term.value
    vendor = connections[db].vendor
    if "__" in f:
        # Advanced search uses the same field/lookup allowlist, type conversion
        # and relationship semantics as the manual Smart Folder builder.
        from archivebox.core.smart_folders import RuleQuery

        field, lookup = f.rsplit("__", 1)
        if public and field not in {
            "title",
            "url",
            "bookmarked_at",
            "created_at",
            "status",
            "permissions",
            "tags__name",
            "domain",
            "output_size",
        }:
            raise ValueError("This advanced field is available only in authenticated administrative searches.")
        return (rules or RuleQuery()).advanced_term(field, lookup, v, stack)
    if f == "domain":
        return SnapshotQuerySet.domain_q(v)
    if f in {"permissions", "status", "title"}:
        return substring(f, v)
    if f == "owner":
        return substring("crawl__created_by__username", v)
    if f in {"after", "before", "bookmarked"}:
        formats = {4: "%Y", 7: "%Y-%m", 10: "%Y-%m-%d"}
        if len(v) not in formats:
            raise ValueError("Use YYYY, YYYY-MM or YYYY-MM-DD")
        start = datetime.strptime(v, formats[len(v)]).replace(tzinfo=UTC)
        if f != "bookmarked":
            return Q(bookmarked_at__gte=start) if f == "after" else Q(bookmarked_at__lt=start)
        # The largest representable date has no exclusive upper bound.
        if start.year == 9999 and (len(v) == 4 or (start.month == 12 and (len(v) == 7 or start.day == 31))):
            return Q(bookmarked_at__gte=start)
        if len(v) == 4:
            stop = start.replace(year=start.year + 1)
        elif len(v) == 7:
            stop = (start + timedelta(days=31)).replace(day=1)
        else:
            stop = start + timedelta(days=1)
        return Q(bookmarked_at__gte=start, bookmarked_at__lt=stop)
    if f in {"tags", "plugins", "filetype"}:
        parts = term.items or v.split(",")
        match_case = has_uppercase(v)
        if not all(parts):
            raise ValueError("Empty list item")
        results = ArchiveResult.objects.filter(snapshot_id=OuterRef("pk"))
        if f == "tags":
            return reduce(
                and_,
                (
                    Q(pk__in=SnapshotTag.objects.filter(substring("tag__name", s, match_case=match_case)).values("snapshot_id"))
                    for s in parts
                ),
            )
        if f == "plugins":
            return reduce(
                and_,
                (
                    Q(
                        Exists(
                            results.filter(
                                substring("plugin", s, match_case=match_case),
                                status="succeeded",
                            ),
                        ),
                    )
                    for s in parts
                ),
            )
        if not all(re.fullmatch(r"[a-zA-Z0-9]+", s) for s in parts):
            raise ValueError("Invalid extension")
        if vendor == "postgresql":
            # The file paths are JSON object keys. Django's key transforms work
            # for known keys, but cannot enumerate arbitrary keys by extension.
            keys_from = """jsonb_object_keys(CASE WHEN jsonb_typeof(output_files) = 'object'
                THEN output_files ELSE '{}'::jsonb END) AS j(key)"""
        else:
            keys_from = "json_each(output_files) AS j"
        comparison, prefix = "lower(j.key) LIKE %s", "%."
        if match_case:
            # SQLite LIKE still folds ASCII; GLOB preserves filename case.
            comparison, prefix = ("j.key GLOB %s", "*.") if vendor == "sqlite" else ("j.key LIKE %s", "%.")
        clause = " OR ".join(comparison for _ in parts)
        keys = RawSQL(
            f"EXISTS (SELECT 1 FROM {keys_from} WHERE {clause})",
            [prefix + (s if match_case else s.lower()) for s in parts],
            output_field=BooleanField(),
        )
        return Q(Exists(results.filter(keys)))
    if f == "meta":
        fields = (
            "url",
            "title",
            "timestamp",
            "notes",
            "status",
            "permissions",
            "bookmarked_at",
            "created_at",
            "modified_at",
            "downloaded_at",
            "fs_version",
            "depth",
            "num_uses_failed",
            "num_uses_succeeded",
            "retry_at",
            "delete_at",
            "output_size",
            "crawl_id",
            "parent_snapshot_id",
            "folder_id",
            "crawl__notes",
            "crawl__label",
            "crawl__created_by__username",
        )
        if public:
            fields = ("url", "title", "timestamp", "status", "permissions", "bookmarked_at", "created_at", "output_size")
        base = reduce(
            or_,
            (substring(Cast(field, TextField()), v) for field in (*fields, "pk")),
        ) | Q(pk__in=SnapshotTag.objects.filter(substring("tag__name", v)).values("snapshot_id"))
        return base if public else base | Q(ConfigContains("config", v)) | Q(ConfigContains("crawl__config", v))
    return None
