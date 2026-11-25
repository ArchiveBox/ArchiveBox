"""Snapshot search expressions shared by web, API, CLI and Smart Folders."""

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache, reduce
from operator import and_, or_

from django.db import connections
from django.db.models import BinaryField, BooleanField, Case, Exists, F, Func, OuterRef, Q, QuerySet, TextField, Value, When
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast, Coalesce, Length, Lower, StrIndex
from django.db.models.lookups import Exact, GreaterThan, IContains, In, IRegex, Regex
from django.db.models.sql import Query
from django.db.models.sql.where import WhereNode

from archivebox.core.models import ArchiveResult, Snapshot, SnapshotQuerySet
from archivebox.core.tag_util import tag_assignments_matching

logger = logging.getLogger(__name__)


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
ALIASES = {"tag": "tags", "site": "domain", "linkedto": "linksto"}
OPERATORS = {
    "folder": ("folder", "Folder name or nested path"),
    "tags": ("tag", "Tag name contains this text"),
    "plugins": ("puzzle", "Successful plugin name contains this text"),
    "owner": ("user", "Username contains this text"),
    "domain": ("globe", "Website domain contains this text"),
    "url": ("link", "Snapshot URL contains this text"),
    "after": ("calendar", "Bookmarked on or after a date"),
    "before": ("calendar", "Bookmarked before a date"),
    "bookmarked": ("calendar", "Bookmarked in a year, month or day"),
    "status": ("check", "Snapshot state"),
    "filetype": ("file", "Saved file extension contains this text"),
    "permissions": ("lock", "Snapshot visibility"),
    "title": ("type", "Title contains this text"),
    "meta": ("database", "Search database metadata"),
    "linksto": ("out", "Outgoing URL contains this text."),
    "linkedfrom": ("link", "Source URL contains this text."),
}


@lru_cache(maxsize=1)
def plugin_operators():
    from archivebox.plugins.discovery import get_plugin_catalog

    catalog = get_plugin_catalog()
    registered, duplicates = {}, set()
    for plugin in catalog.values():
        operators = plugin.manifest.get("search_operators")
        if operators is None:
            continue
        if not isinstance(operators, dict) or not catalog.command(plugin.name, "search_scope"):
            logger.warning("Ignoring invalid search operator declarations for %s", plugin.name)
            continue
        for key, display in operators.items():
            if (
                not re.fullmatch(r"[a-z][a-z0-9_]*", key)
                or "__" in key
                or key in (OPERATORS.keys() | ALIASES.keys() | {"deep", "word", "literal"})
                or not isinstance(display, dict)
                or not all(isinstance(display.get(field), str) and display[field] for field in ("icon", "description"))
            ):
                logger.warning("Ignoring invalid search operator %r from %s", key, plugin.name)
                continue
            if key in registered or key in duplicates:
                registered.pop(key, None)
                duplicates.add(key)
                logger.warning("Ignoring duplicate search operator %r from %s", key, plugin.name)
                continue
            registered[key] = (plugin, display["icon"], display["description"])
    return registered


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
        if (
            field != "deep"
            and field not in OPERATORS
            and not re.fullmatch(r"[a-z][a-z0-9_]*__[a-z_]+", field)
            and field not in plugin_operators()
        ):
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
            if field == "deep":
                field = "literal"
            i += 1
        if not value:
            raise ValueError(f"Empty {field}")
        # Bookmarked searches from the old UI now use ordinary indexed text.
        return Term("word" if field == "deep" else field, value)

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


def sql_predicate_cost(predicate):
    """Prefer column checks over related-row probes and JSON iteration within each WHERE group."""
    # Inspect the actual proof: a metadata term can compile to a simple
    # hostname seek in one wave and recursive JSON traversal in the next.
    json_iterations = subqueries = expressions = 0

    def count(expr):
        nonlocal json_iterations, subqueries, expressions
        expressions += 1
        if isinstance(expr, (ConfigContains, OutputPathExists)):
            json_iterations += 1
        if isinstance(expr, QuerySet):
            expr = expr.query
        if isinstance(expr, Query):
            subqueries += 1
            count(expr.where)
        elif isinstance(expr, (Q, WhereNode)):
            for child in expr.children:
                count(child)
        elif isinstance(expr, tuple) and len(expr) == 2 and isinstance(expr[0], str):
            count(expr[1])
        elif hasattr(expr, "get_source_expressions"):
            for child in expr.get_source_expressions():
                count(child)

    count(predicate)
    return json_iterations, subqueries, expressions


def sql_bounds(node, sql, text=None):
    """Bound membership before file/index I/O. NOT reverses possible and certain."""

    def visit(node, negated=False):
        if isinstance(node, Term):
            bounds = (sql[node], sql[node]) if node in sql else ((text or {}).get(node, False), True)
            return tuple(not q if isinstance(q, bool) else ~q for q in reversed(bounds)) if negated else bounds
        if node.op == "not":
            return visit(node.args[0], not negated)

        # Push negation to the leaves using De Morgan's laws. Flatten only
        # associative groups: distributing AND over OR could grow exponentially.
        disjunction = (node.op == "or") != negated
        connector = Q.OR if disjunction else Q.AND
        bounds = [visit(arg, negated) for arg in node.args]

        def combine(column):
            if any(part is disjunction for part in column):
                return disjunction
            parts = []
            for part in column:
                if isinstance(part, Q):
                    if part.children and not part.negated and part.connector == connector:
                        parts.extend(part.children)
                    else:
                        parts.append(part)
            if not parts:
                return not disjunction
            if len(parts) == 1 and isinstance(parts[0], Q):
                return parts[0]
            # Short-circuit inexpensive proofs/rejections first, including
            # siblings that were originally inside a parenthesized group.
            if len(parts) > 1:
                parts.sort(key=sql_predicate_cost)
            return Q(*parts, _connector=connector)

        lower = combine(tuple(pair[0] for pair in bounds))
        if all(pair[0] is pair[1] for pair in bounds):
            return lower, lower
        return lower, combine(tuple(pair[1] for pair in bounds))

    return visit(node)


def has_uppercase(value):
    # Each operator decides from its decoded value. Field names, Boolean
    # keywords and neighboring operands never affect the decision.
    return any(char.isupper() for char in value)


@lru_cache(maxsize=128)
def literal_pattern(value):
    return re.compile(re.escape(value), 0 if has_uppercase(value) else re.IGNORECASE)


class InsensitiveLiteral(Func):
    output_field = BooleanField()

    def as_sql(self, compiler, connection, **extra_context):
        text, needle = self.get_source_expressions()
        return compiler.compile(IRegex(text, Value(re.escape(needle.value))))

    def as_sqlite(self, compiler, connection, **extra_context):
        text, needle = self.get_source_expressions()
        if not needle.value.isascii():
            return self.as_sql(compiler, connection)
        # SQLite's built-in lower() handles ASCII in C. Only non-ASCII
        # haystacks can need Django's Python Unicode regex after a miss.
        return compiler.compile(
            Case(
                When(GreaterThan(StrIndex(Lower(text), Value(needle.value.lower())), Value(0)), then=True),
                When(Exact(Length(text), Length(Cast(text, BinaryField()))), then=False),
                default=IRegex(text, Value(re.escape(needle.value))),
            ),
        )


def substring(field, value, *, match_case=None):
    if match_case is None:
        match_case = has_uppercase(value)
    text = Coalesce(field, Value(""), output_field=TextField())
    if match_case:
        return Q(GreaterThan(StrIndex(text, Value(value)), Value(0)))
    return Q(InsensitiveLiteral(text, Value(value)))


class HostnameFragmentIn(In):
    """Keep the indexed scan for collections and check known page rows directly."""

    def __init__(self, lhs, rhs, fragments):
        self.fragments = tuple(fragments)
        super().__init__(lhs, rhs)

    def as_sql(self, compiler, connection):
        if connection.vendor == "sqlite" and getattr(compiler.query, "_archivebox_candidate_row", False):
            return compiler.compile(WhereNode([IContains(self.lhs, fragment) for fragment in self.fragments], connector=Q.OR))
        return super().as_sql(compiler, connection)


def domain_substring(value, db):
    from archivebox.core.domain_grouping import domain_authority_from_key
    from archivebox.misc.util import equivalent_urls

    hosts = Snapshot.objects.using(db)
    keys = hosts.none()
    matching = Q(pk__in=[])
    idn_terms = []
    fragments = []
    fragment_only = True
    for part in value.split(","):
        term = part.strip().lower()
        if not term:
            continue
        if term.startswith("*."):
            fragment_only = False
            matching |= SnapshotQuerySet.domain_q(term)
            continue
        if not term.isascii() or "xn--" in term:
            fragment_only = False
            idn_terms.append(term)
        elif re.fullmatch(r"[\w-]+", term):
            # Reversing labels and moving the port preserves a single
            # fragment. Read the hostname index without fetching URLs.
            keys |= hosts.filter(reversed_domain__icontains=term)
            fragments.append(term)
        else:
            fragment_only = False
            # A dot or colon can span labels or the port boundary; prove
            # the match against the authority in its original order.
            keys |= hosts._domain_key_candidates(term).filter(hosts.domain_rule_q("icontains", term))
    if idn_terms:
        # Encoding a partial Unicode label changes its punycode. Compare the
        # two spellings of each distinct IDN host, never every snapshot URL.
        idns = hosts.filter(Q(reversed_domain__contains="xn--") | Q(reversed_domain__regex=r"[^\x01-\x7f]"))
        matched = []
        for key in idns.order_by("reversed_domain").values_list("reversed_domain", flat=True).distinct().iterator():
            spellings = equivalent_urls("//" + domain_authority_from_key(key))
            if any(term in spelling[2:].lower() for term in idn_terms for spelling in spellings):
                matched.append(key)
        matching |= Q(reversed_domain__in=matched)
    indexed = keys.order_by().values("reversed_domain").distinct()
    if fragment_only and fragments and connections[db].vendor == "sqlite":
        # Test only the candidate's hostname instead of rebuilding every
        # matching hostname in the archive for each small paginator probe.
        return Q(HostnameFragmentIn(F("reversed_domain"), indexed.query, fragments))
    return matching | Q(reversed_domain__in=indexed)


def url_substring_hint(value, db):
    """An indexed subset of URL matches. Always verify with the literal predicate."""
    if re.fullmatch(r"[\w-]+(?:\.[\w-]+)+", value):
        try:
            return SnapshotQuerySet.domain_q(f"*.{value}")
        except ValueError:
            return None
    if value.lower().startswith(("https://", "http://")):
        prefixes = (value,)
    elif re.match(r"^[\w-]+(?:\.[\w-]+)*(?:[/:?#]|$)", value):
        # An omitted scheme still allows two small seeks, including a partial
        # host or a host followed by a path. Other occurrences come later.
        prefixes = ("https://" + value, "http://" + value)
    else:
        return None
    return reduce(
        or_,
        (
            Q(url__gte=p, url__lt=url_prefix_upper_bound(p)) if connections[db].vendor == "sqlite" and p.isascii() else Q(url__startswith=p)
            for p in prefixes
        ),
    )


def url_prefix_upper_bound(prefix):
    return prefix[:-1] + chr(ord(prefix[-1]) + 1) if prefix else prefix


class ConfigContains(Func):
    """Django can address a known JSON path; here we need every scalar value."""

    output_field = BooleanField()
    arity = 2

    def __init__(self, field, needle):
        self.needle = needle
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
            # Four consecutive ASCII letters can only come from a string or
            # boolean (SQLite renders non-finite numbers as at most "Inf").
            # If that text is absent from ASCII JSON, only a Unicode escape
            # could decode to it. Always check the scalar itself for positives:
            # matching an object key or text spanning values is insufficient.
            anchor = re.search(r"[A-Za-z]{4,}", self.needle)
            if anchor:
                guard = (
                    f"(typeof({column}) != 'text' OR instr(lower({column}), %s) OR instr({column}, %s) "
                    f"OR length({column}) != length(CAST({column} AS BLOB)))"
                )
                return f"({guard} AND EXISTS ({sql}))", (
                    *lhs_params,
                    *lhs_params,
                    anchor.group().lower(),
                    *lhs_params,
                    r"\u",
                    *lhs_params,
                    *lhs_params,
                    *lhs_params,
                    *rhs_params,
                )
        return f"EXISTS ({sql})", (*lhs_params, *rhs_params)


class OutputPathExists(Func):
    """Apply a text predicate to recorded paths, which are JSON keys, never metadata values."""

    output_field = BooleanField()

    def as_sql(self, compiler, connection, **extra_context):
        column, params = compiler.compile(self.source_expressions[0])
        predicate, values = compiler.compile(self.source_expressions[1])
        if connection.vendor == "postgresql":
            keys = f"jsonb_object_keys(CASE WHEN jsonb_typeof({column}) = 'object' THEN {column} ELSE '{{}}'::jsonb END) AS j(key)"
            params = (*params, *params)
        else:
            keys = f"json_each({column}) AS j"
            predicate = f"typeof(j.key) = 'text' AND ({predicate})"
        return f"EXISTS (SELECT 1 FROM {keys} WHERE {predicate})", (*params, *values)


def recorded_path_contains(value):
    key = RawSQL("j.key", (), output_field=TextField())
    results = ArchiveResult.objects.filter(snapshot_id=OuterRef("pk")).filter(OutputPathExists("output_files", substring(key, value)))
    return Q(Exists(results))


def matching_tag_assignments(value, *, match_case=None):
    return tag_assignments_matching(substring("name", value, match_case=match_case))


def tags_predicate(term, *, exact=False):
    parts = term.items or term.value.split(",")
    if not all(parts):
        raise ValueError("Empty list item")
    match_case = has_uppercase(term.value)
    predicates = (Q(name=part) if exact else substring("name", part, match_case=match_case) for part in parts)
    return reduce(and_, (Q(pk__in=tag_assignments_matching(predicate).values("snapshot_id")) for predicate in predicates))


def text_metadata(term, *, public):
    # These are positive witnesses for ordinary or quoted text. An absent
    # metadata match still leaves the configured index free to confirm the row.
    fields = ["title", "url", "timestamp", "crawl__created_by__username"]
    if not public:
        fields.extend(("notes", "crawl__notes", "crawl__label"))
    # A candidate page already has snapshot IDs. Probe their assignments
    # instead of materializing every matching assignment in the collection.
    tags = matching_tag_assignments(term.value).filter(snapshot_id=OuterRef("pk"))
    return reduce(or_, (substring(f, term.value) for f in fields)) | Q(Exists(tags)) | recorded_path_contains(term.value)


def sql_leaf(term, db, *, rules=None, stack=(), public=False):
    f, v = term.field, term.value
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
    if f == "folder":
        from archivebox.core.smart_folders import RuleQuery

        return (rules or RuleQuery()).named_folders(v, stack, public=public)
    if f == "domain":
        return domain_substring(v, db)
    if f in {"permissions", "status", "title", "url"}:
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
    if f == "tags":
        return tags_predicate(term)
    if f in {"plugins", "filetype"}:
        parts = term.items or v.split(",")
        match_case = has_uppercase(v)
        if not all(parts):
            raise ValueError("Empty list item")
        results = ArchiveResult.objects.filter(snapshot_id=OuterRef("pk"))
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
        # Recorded paths include directories and compound filenames. Anchor
        # the match to the last extension so e.g. report.pdf.html is HTML.
        needles = [re.escape(part) for part in parts if "." not in part and "/" not in part]
        if not needles:
            return Q(pk__in=[])
        pattern = rf"\.[^./]*(?:{'|'.join(needles)})[^./]*\Z"
        lookup = Regex if match_case else IRegex
        keys = lookup(RawSQL("j.key", (), output_field=TextField()), Value(pattern))
        return Q(Exists(results.filter(OutputPathExists("output_files", keys))))
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
        )
        if public:
            fields = ("url", "title", "timestamp", "status", "permissions", "bookmarked_at", "created_at", "output_size")
        base = reduce(
            or_,
            (substring(Cast(field, TextField()), v) for field in (*fields, "pk")),
        ) | Q(pk__in=matching_tag_assignments(v).values("snapshot_id"))
        if public:
            return base
        from archivebox.crawls.models import Crawl

        # A single crawl can own thousands of snapshots with the same metadata.
        # Match its scalar config values and owner once, then test membership by
        # crawl ID while walking snapshots in the requested display order.
        crawl_fields = ("notes", "label", "created_by__username")
        crawl_matches = reduce(or_, (substring(Cast(field, TextField()), v) for field in crawl_fields)) | Q(ConfigContains("config", v))
        return base | Q(ConfigContains("config", v)) | Q(crawl_id__in=Crawl.objects.filter(crawl_matches).order_by().values("pk"))
    return None
