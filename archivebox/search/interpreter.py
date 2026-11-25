"""Plan one search against an already permission-filtered Snapshot queryset."""

import json
import logging
import math
import shutil
import subprocess
import sys
import time
import threading
from collections import Counter, defaultdict
from contextlib import nullcontext
from functools import cached_property
from itertools import batched, chain, islice
from pathlib import Path
from subprocess import SubprocessError

from django.db import connections
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db.models import Case, Exists, OuterRef, Q, QuerySet, Value, When

from archivebox.config.common import get_config
from archivebox.config.constants import CONSTANTS
from archivebox.plugins.discovery import get_plugin_app, get_plugin_catalog
from archivebox.search.backends import get_backend, normalize_search_backend_name, search_backend_command_env
from archivebox.search.language import (
    Term,
    has_uppercase,
    leaves,
    literal_pattern,
    parse,
    simplify,
    sql_bounds,
    sql_leaf,
    substring,
    tags_predicate,
    text_metadata,
    url_substring_hint,
)

logger = logging.getLogger(__name__)
PAGE_SIZE = 64
# External work is shared by every Boolean branch. Metadata-only queries remain
# ordinary lazy Django queries and never consume this file budget.
DISK_LIMITS = {"files": 96, "entries": 512, "bytes": 4 << 20}
MAX_SECONDS = 8.0
SCAN_SECONDS = 2.0
SONIC_FALLBACK_CANDIDATES = 32
# Only external work competes for these slots. A missing or slow mounted drive
# must not block ordinary metadata searches or multiply disk load per browser.
EXTERNAL_SLOTS = threading.BoundedSemaphore(2)
STALL_SECONDS = 30.0


def indexed_predicate(model, predicate):
    """Recognize direct B-tree probes in a compiled Django Q, regardless of operator name."""
    for part in predicate.children:
        if isinstance(part, Q):
            if not indexed_predicate(model, part):
                return False
        elif isinstance(part, tuple) and isinstance(part[0], str):
            field_name, _, lookup = part[0].partition("__")
            if lookup not in ("", "exact", "in", "gt", "gte", "lt", "lte", "range"):
                return False
            try:
                field = model._meta.pk if field_name == "pk" else model._meta.get_field(field_name)
            except FieldDoesNotExist:
                return False
            # Generated domains and compound indexes are declared on Meta.
            # An unconditional leading column supports the same B-tree seek.
            if not (
                field.primary_key
                or field.unique
                or field.db_index
                or any(i.fields and not i.condition and i.fields[0].lstrip("-") == field.name for i in model._meta.indexes)
            ):
                return False
        else:
            return False
    return bool(predicate.children)


def positive_terms(node, negated=False):
    if isinstance(node, Term):
        if not negated:
            yield node
        return
    for child in node.args:
        yield from positive_terms(child, negated != (node.op == "not"))


def sql_snapshot_search(scope, query, *, public=False, ranked=False):
    """Return a lazy metadata queryset, or defer external work and syntax errors to the stream."""
    try:
        return SnapshotSearch(scope, query, public=public).sql_queryset(ranked=ranked)
    except (ValueError, ValidationError):
        return None


class SnapshotSearch:
    def __init__(
        self,
        scope,
        query,
        *,
        config=None,
        stop_event=None,
        rules=None,
        stack=(),
        public=False,
        streaming=False,
        allow_sonic_fallback=False,
        progress=None,
    ):
        self.progress = progress
        self.scope = scope
        self.tree = parse(query)
        self.terms = tuple(dict.fromkeys(leaves(self.tree)))
        if rules is None and any(t.field == "folder" or "__" in t.field for t in self.terms):
            from archivebox.core.smart_folders import RuleQuery

            rules = RuleQuery()
        self.sql = {t: q for t in self.terms if (q := sql_leaf(t, scope.db, rules=rules, stack=stack, public=public)) is not None}
        self.evidence = {t: text_metadata(t, public=public) for t in self.terms if t.field in {"word", "literal"}}
        self.url_hints = {}
        self.indexed_evidence = {}
        for term in self.terms:
            if term.field == "tags":
                # An exact spelling is sufficient evidence for its substring.
                # Keep the complete predicate for other spellings and overlaps.
                self.indexed_evidence[term] = tags_predicate(term, exact=True)
                continue
            if term.field not in {"meta", "url", "word", "literal", "linkedfrom", "linksto"}:
                continue
            hint = url_substring_hint(term.value, scope.db)
            if term.field == "meta" and term.value.isascii() and term.value.isalnum():
                # Walk the narrow hostname index, then look up snapshots for
                # the matching hosts. A label can occur anywhere in a domain.
                domains = (
                    scope.model.objects.using(scope.db)
                    .filter(reversed_domain__icontains=term.value)
                    .order_by()
                    .values("reversed_domain")
                    .distinct()
                )
                hint = Q(reversed_domain__in=domains)
            if hint is not None:
                self.url_hints[term] = hint
            if term.field in {"meta", "url", "word", "literal"}:
                if hint is not None:
                    self.indexed_evidence[term] = hint & substring("url", term.value)
                continue
            endpoints = self.link_endpoints(term)
            if hint is not None:
                indexed_endpoints = self.link_endpoints(term, scope=self.index_probe_scope).filter(hint)
                # SQLite materializes the RHS of IN before yielding one child.
                # Start with a page of matching endpoints; the complete
                # predicate below still covers every source and every file.
                if term.field == "linkedfrom":
                    children = self.index_probe_scope.filter(parent_snapshot_id=OuterRef("pk"))
                    indexed_endpoints = indexed_endpoints.filter(Exists(children))
                    self.indexed_evidence[term] = Q(parent_snapshot_id__in=indexed_endpoints.values("pk")[:PAGE_SIZE])
                else:
                    # Limit distinct sources, so hundreds of children sharing
                    # a parent do not crowd other matching sources off page one.
                    parents = indexed_endpoints.exclude(parent_snapshot_id=None).values("parent_snapshot_id").distinct()
                    self.indexed_evidence[term] = Q(pk__in=parents[:PAGE_SIZE])
            # Only actual parents/children can provide database link evidence.
            # Keep the broader substring pass for paths, lookalikes and ports.
            if term.field == "linkedfrom":
                children = scope.order_by().filter(parent_snapshot_id__isnull=False)
                endpoints = endpoints.filter(pk__in=children.values("parent_snapshot_id").distinct())
            self.evidence[term] = self.recorded_links(term, endpoints)
        self.config = config
        self.streaming = streaming
        self.stop_event = stop_event
        self.partial = False
        self.usage = Counter()
        # Replace the pair together so the HTTP stream always samples one batch.
        self.archive_batch = (0, 0)
        self.link_cache = {}
        self.reverse = {}
        self.legacy_hits = {}
        self.word_hits = defaultdict(set)
        self.exhausted_words = set()
        self.hinted_ids = {}
        self.scan_deadline = None
        self.allow_sonic_fallback = allow_sonic_fallback and streaming and not public
        self.sonic_handshake = None
        self.sonic_started = None
        self.fallback_candidates = SONIC_FALLBACK_CANDIDATES
        self.deadline = math.inf

    def phase(self, name, provider="", **timing):
        return self.progress.phase(name, provider, **timing) if self.progress else nullcontext()

    @cached_property
    def env(self):
        self.config = self.config or get_config()
        return search_backend_command_env(config=self.config)

    @cached_property
    def backend(self):
        self.config = self.config or get_config()
        return get_backend(config=self.config)

    @cached_property
    def sonic_fallback(self):
        if not self.allow_sonic_fallback or self.backend is None or self.backend.name != "search_backend_sonic":
            return None
        if normalize_search_backend_name(self.config.get("SEARCH_BACKEND_ENGINE")) != "sonic":
            return None
        scanner = get_plugin_catalog().get("search_backend_ripgrep")
        if not scanner or not scanner.config.search_scan or not self.config.get(scanner.enabled_key, True):
            return None
        return scanner

    def observe_sonic(self, connected):
        if self.sonic_handshake is not None or self.sonic_started is None:
            return
        if connected:
            self.sonic_handshake = True
        elif shutil.which(self.env.get("RIPGREP_BINARY", "rg"), path=self.env.get("PATH")):
            # Do not enter the scanner's dependency resolver for a missing binary.
            self.sonic_handshake = False
            self.scan_deadline = self.sonic_started + SCAN_SECONDS

    def active(self):
        if self.stop_event and self.stop_event.is_set():
            return False
        if not self.streaming and time.monotonic() >= self.deadline:
            self.partial = True
            return False
        return True

    def queryset(self):
        queryset = self.sql_queryset()
        if queryset is not None:
            return queryset
        # Forms, exports and REST pagination require a queryset; the SSE path
        # consumes stream() directly and publishes before expensive reads finish.
        ids = list(self.stream())
        qs = self.scope.filter(pk__in=ids)
        if not self.scope.query.order_by and ids:
            # Keep SQL size bounded even for broad metadata branches.
            head = ids[:500]
            qs = qs.order_by(Case(*(When(pk=pk, then=Value(i)) for i, pk in enumerate(head)), default=Value(len(head))), "pk")
        qs.search_partial = self.partial
        return qs

    @cached_property
    def index_probe_scope(self):
        # On SQLite a low-selectivity permissions equality can displace BOTH
        # the hostname and parent indexes. Seek in the indexed field first,
        # checking the original scope by PK for each candidate (including
        # both ends of a relationship). PostgreSQL can plan the join itself.
        if self.scope.query.where and connections[self.scope.db].vendor == "sqlite":
            permitted = self.scope.filter(pk=OuterRef("pk"))
            return self.scope.model._base_manager.using(self.scope.db).filter(Exists(permitted))
        return self.scope

    @cached_property
    def indexed_bounds(self):
        direct = {term: q for term, q in self.sql.items() if term.field != "tags" and indexed_predicate(self.scope.model, q)}
        quick, narrow = sql_bounds(self.tree, direct, self.indexed_evidence)
        if quick is False and self.indexed_evidence:
            # An unindexed sibling (url:... AND title:..., for example) can
            # still be checked cheaply against a bounded page of candidates.
            certain, _ = sql_bounds(self.tree, self.sql, self.evidence)
            hints = [self.indexed_evidence[t] for t in positive_terms(self.tree) if t in self.indexed_evidence]
            if hints and isinstance(certain, Q):
                candidates = self.witnesses(Q(*hints, _connector=Q.OR), indexed=True)[:PAGE_SIZE]
                quick = Q(pk__in=candidates) & certain
        return quick, narrow

    def sql_queryset(self, *, ranked=False):
        # An unordered metadata search can publish URL and title matches
        # before inspecting every config value. A column sort must page the
        # entire predicate, including negation and Boolean combinations.
        if ranked and isinstance(self.tree, Term) and self.tree.field == "meta":
            return None
        if ranked and any(t.field in {"meta", "url"} for t in self.indexed_evidence) and isinstance(self.indexed_bounds[0], Q):
            return None
        if len(self.sql) == len(self.terms):
            return self.scope.filter(sql_bounds(self.tree, self.sql)[1])
        return None

    def disk_budget_available(self):
        return self.streaming or all(self.usage[name] < maximum for name, maximum in DISK_LIMITS.items())

    def scan_seconds_left(self):
        # Start the single scan budget at first use, after cheap indexed/SQL
        # matches. Every branch, candidate page and semaphore wait shares it.
        now = time.monotonic()
        if self.scan_deadline is None:
            self.scan_deadline = now + SCAN_SECONDS
            if not self.streaming:
                self.scan_deadline = min(self.deadline, self.scan_deadline)
        return max(0, self.scan_deadline - now)

    def scan_available(self):
        return self.scan_seconds_left() > 0 and all(self.usage[key] < limit for key, limit in DISK_LIMITS.items())

    def command_records(self, command, payload, *, env=None, scan=False, activity="provider"):
        from abx_dl.execution import iter_plugin_command

        if not self.streaming and not scan:
            lines = iter_plugin_command(
                command,
                stdin=[json.dumps(payload)],
                cwd=CONSTANTS.DATA_DIR,
                env=env,
                stop_event=self.stop_event,
                timeout=max(0.01, self.deadline - time.monotonic()),
            )
            try:
                for line in lines:
                    yield json.loads(line)
            finally:
                lines.close()
            return

        with self.phase("queue", timeout=self.scan_seconds_left() if scan else None):
            while not EXTERNAL_SLOTS.acquire(timeout=min(0.1, self.scan_seconds_left()) if scan else 0.1):
                if not self.active() or (scan and not self.scan_available()):
                    return
        last_activity = time.monotonic()
        cancellation = self.stop_event

        class ScanCancellation:
            def is_set(self):
                if cancellation and cancellation.is_set():
                    return True
                if time.monotonic() - last_activity > STALL_SECONDS:
                    raise TimeoutError("The search provider stopped responding")
                return False

        try:
            if scan and not self.scan_available():
                return
            lines = iter_plugin_command(
                command,
                stdin=[json.dumps(payload)],
                cwd=CONSTANTS.DATA_DIR,
                env=env,
                stop_event=ScanCancellation(),
                timeout=self.scan_seconds_left() if scan else None,
            )
            if self.progress:
                lines = self.progress.reading(
                    lines,
                    activity,
                    command.plugin_name if activity == "provider" else "",
                    timeout=self.scan_seconds_left() if scan else None,
                    idle_since=lambda: (last_activity, STALL_SECONDS),
                )
            try:
                for line in lines:
                    last_activity = time.monotonic()
                    record = json.loads(line)
                    if isinstance(record, dict) and record.get("progress") is True:
                        continue
                    yield record
            finally:
                lines.close()
        except subprocess.TimeoutExpired:
            if not scan:
                raise
            self.partial = True
        finally:
            EXTERNAL_SLOTS.release()

    def link_rows(self, snapshots):
        # A connected search can traverse many small plugin outputs. Amortize
        # interpreter startup across a DB page, publishing each source as read.
        root = CONSTANTS.ARCHIVE_DIR
        for batch in batched(snapshots, PAGE_SIZE):
            paths, pending = [], []
            for snapshot in batch:
                if not self.active():
                    return
                folders = snapshot.storage_path_candidates()
                if any(not folder.is_relative_to(root) or ".." in folder.parts for folder in folders):
                    yield snapshot, set(), False
                    continue
                path = [str(folder.relative_to(root)) for folder in folders]
                if self.streaming:
                    paths.append(path)
                    pending.append(snapshot)
                else:
                    urls, done = self.preview_links(snapshot, path)
                    yield snapshot, urls, done
            if not pending:
                continue
            from abx_dl.models import PluginCommand

            reader = Path(__file__).with_name("outlinks.py")
            command = PluginCommand(name="outlinks", plugin_name="archivebox", path=Path(sys.executable), args=["-I", str(reader)])
            records = self.command_records(command, {"root": str(root), "snapshots": paths}, activity="links")
            try:
                self.archive_batch = (0, len(pending))
                for index, snapshot in enumerate(pending, 1):
                    urls = set()
                    for item in records:
                        if isinstance(item, str):
                            urls.add(item)
                        else:
                            self.archive_batch = (index, len(pending))
                            yield snapshot, urls, item["complete"]
                            break
                    else:
                        if self.active():
                            raise RuntimeError("Outlink reader stopped before completing its batch")
                        return
            finally:
                records.close()

    def preview_links(self, snapshot, path):
        if snapshot.pk in self.link_cache:
            return self.link_cache[snapshot.pk]
        if not self.disk_budget_available():
            return set(), False
        payload = {
            "root": str(CONSTANTS.ARCHIVE_DIR),
            "snapshot": path,
            "byte_limit": DISK_LIMITS["bytes"] - self.usage["bytes"],
            "file_limit": DISK_LIMITS["files"] - self.usage["files"],
        }
        try:
            worker = subprocess.run(
                [sys.executable, "-I", str(Path(__file__).with_name("outlinks.py"))],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=True,
                timeout=max(0.01, self.deadline - time.monotonic()),
            )
            result = json.loads(worker.stdout)
            self.usage.update(result["usage"])
            self.link_cache[snapshot.pk] = set(result["links"]), result["complete"]
        except (SubprocessError, ValueError, OSError):
            self.link_cache[snapshot.pk] = set(), False
        return self.link_cache[snapshot.pk]

    @staticmethod
    def recorded_links(term, endpoints):
        if term.field == "linkedfrom":
            return Q(parent_snapshot_id__in=endpoints.values("pk"))
        # Walk distinct recorded parents through the relationship index. Each
        # candidate needs just one child satisfying the scoped URL predicate.
        parents = (
            endpoints.model.objects.using(endpoints.db).exclude(parent_snapshot_id=None).order_by().values("parent_snapshot_id").distinct()
        )
        return Q(pk__in=parents) & Q(Exists(endpoints.filter(parent_snapshot_id=OuterRef("pk"))))

    def link_endpoints(self, term, *, scope=None):
        scope = self.scope if scope is None else scope
        return scope.order_by().filter(substring("url", term.value), Q(url__istartswith="http://") | Q(url__istartswith="https://"))

    def sources(self, term):
        qs = (
            self.link_endpoints(term)
            .select_related(None)
            .select_related("crawl__created_by")
            .only("pk", "url", "fs_version", "timestamp", "bookmarked_at", "created_at", "crawl__created_by__username")
            .order_by("pk")
        )
        if self.streaming and term in self.url_hints:
            # Captures with no parent edges still have plugin outputs. Read
            # the first indexed source page before searching unrelated URLs.
            first = list(qs.filter(self.url_hints[term]).order_by()[:PAGE_SIZE])
            yield from first
            qs = qs.exclude(pk__in=[snap.pk for snap in first])
        cursor = None
        while self.active():
            page = list((qs.filter(pk__gt=cursor) if cursor else qs)[:PAGE_SIZE])
            if not page:
                return
            yield from page
            cursor = page[-1].pk

    def target_batches(self, term, *, report_sources=False):
        seen, complete = set(), True
        for _, links, done in self.link_rows(self.sources(term)):
            if report_sources and self.progress:
                self.progress.checked += 1
            complete &= done
            new = links - seen
            seen.update(new)
            if new:
                yield new
            if not self.disk_budget_available():
                complete = False
                break
        self.reverse[term] = seen, complete and self.active()

    def provider(self, backend, terms, rows):
        """Yield evidence from registered commands. An omitted answer is unknown."""
        from abx_dl.execution import iter_plugin_command

        if not backend or not rows or not terms or not self.active():
            return
        command = get_plugin_catalog().command(backend.name, "search_candidates")
        scan = backend.config.search_scan
        if scan and (not command or not self.scan_available()):
            self.partial = True
            return
        if not command:
            # Older third-party indexes still supply positive evidence via
            # their registered search command. A limited posting list cannot prove NOT.
            command = get_plugin_catalog().command(backend.name, "search")
            for term in terms:
                if not command or term.field != "word" or has_uppercase(term.value):
                    continue
                if term not in self.legacy_hits:
                    iterator = iter_plugin_command(
                        command,
                        arguments={"query": term.value, "search_mode": "contents"},
                        env=self.env,
                        cwd=CONSTANTS.DATA_DIR,
                        timeout=MAX_SECONDS if self.streaming else max(0.01, self.deadline - time.monotonic()),
                        stop_event=self.stop_event,
                    )
                    if self.progress:
                        iterator = self.progress.reading(iterator, "provider", backend.name, timeout=MAX_SECONDS)
                    try:
                        self.legacy_hits[term] = {
                            str(pk).replace("-", ""): 1 / rank
                            for rank, pk in enumerate(iterator if self.streaming else islice(iterator, 500), 1)
                        }
                    finally:
                        iterator.close()
                for pk in rows:
                    if pk in self.legacy_hits[term]:
                        yield pk, {term: True}, {term: self.legacy_hits[term][pk]}
            return
        keys = {str(i): term for i, term in enumerate(terms)}
        candidates = []
        for pk, snap in rows.items():
            candidate = {"id": pk}
            if scan:
                # Derive the path from the DB. The child opens it under the
                # archive root so blocked storage I/O is covered by its timeout.
                candidate["path"] = str(snap.get_storage_path_for_version(snap.fs_version))
            candidates.append(candidate)
        unbounded_stream = self.streaming and not scan
        payload = {
            "streaming": unbounded_stream,
            "terms": [{"key": k, "mode": t.field, "value": t.value} for k, t in keys.items()],
            "candidates": candidates,
            "limits": {
                **{k: v if unbounded_stream else max(0, v - self.usage[k]) for k, v in DISK_LIMITS.items()},
                "seconds": self.scan_seconds_left()
                if scan
                else MAX_SECONDS
                if self.streaming
                else max(0.01, self.deadline - time.monotonic()),
                "per_file": 512 << 10,
            },
        }
        if scan:
            payload["archive_root"] = str(CONSTANTS.ARCHIVE_DIR)
        checked = set()
        self.archive_batch = (0, len(rows))
        iterator = self.command_records(command, payload, env=self.env, scan=scan, activity="files" if scan else "provider")
        try:
            for record in iterator:
                pk = str(record["id"]).replace("-", "")
                if pk not in rows:
                    continue
                checked.add(pk)
                self.archive_batch = (len(checked), len(rows))
                for key in DISK_LIMITS:
                    self.usage[key] += max(0, int(record.get("usage", {}).get(key, 0)))
                matches = {keys[k]: v for k, v in record.get("matches", {}).items() if k in keys and isinstance(v, bool)}
                scores = {
                    keys[k]: v
                    for k, v in record.get("scores", {}).items()
                    if k in keys and isinstance(v, (float, int)) and math.isfinite(v)
                }
                yield pk, matches, scores
        finally:
            iterator.close()

    def scan_content_ids(self, backend):
        """Legacy contents-only search uses the same scoped, bounded candidate command."""
        (term,) = self.terms
        cursor = None
        snapshots = self.scope.select_related("crawl__created_by").order_by("pk")
        while self.active() and self.scan_available():
            page = list((snapshots.filter(pk__gt=cursor) if cursor else snapshots)[:PAGE_SIZE])
            if not page:
                return
            rows = {snap.pk.hex: snap for snap in page}
            for pk, evidence, _ in self.provider(backend, (term,), rows):
                if evidence.get(term):
                    yield pk
            cursor = page[-1].pk
        self.partial = True

    def stream(self):
        qs = self.scope
        with self.phase("planning"):
            matches = self.sql_queryset()
        if matches is not None:
            if not qs.query.order_by and isinstance(self.tree, Term) and self.tree.field == "meta":
                value = self.tree.value
                url_match = substring("url", value)
                early = set()
                tiers = []
                if value.isascii() and value.isalnum():
                    # Streaming a bounded hostname index scan yields the first
                    # matching label without materializing all distinct hosts.
                    tiers.append((Q(reversed_domain__icontains=value) & url_match, "reversed_domain"))
                elif hint := self.indexed_evidence.get(self.tree):
                    tiers.append((hint, "reversed_domain"))
                tiers.extend([(url_match, "url"), (substring("title", value), "title")])
                for predicate, order in tiers:
                    # Bound the IDs retained for exclusion. Each tier proves
                    # membership by itself; later pages keep every other match.
                    rows = self.index_probe_scope.filter(predicate).order_by(order, "pk").values_list("pk", flat=True)[:PAGE_SIZE]
                    for pk in rows.iterator(chunk_size=1):
                        if not self.active():
                            return
                        if pk not in early:
                            early.add(pk)
                            yield pk
                matches = matches.exclude(pk__in=early).order_by("pk")
            elif not qs.query.order_by and (
                self.sql_queryset(ranked=True) is None
                or (any(term.field == "tags" for term in self.indexed_evidence) and isinstance(self.indexed_bounds[0], Q))
            ):
                # Keep subsequent queries disjoint, but publish the first index
                # hit immediately even if the rest of the bounded probe is slow.
                head = set()
                for pk in self.indexed_witnesses(self.indexed_bounds[0]):
                    head.add(pk)
                    yield pk
                matches = matches.exclude(pk__in=head).order_by()
            # On a sparse predicate, fetching a batch delays its first match
            # until SQLite finds the last one (or exhausts the collection).
            if not self.active():
                return
            for pk in matches.values_list("pk", flat=True).iterator(chunk_size=1 if self.streaming else PAGE_SIZE):
                if not self.active():
                    return
                yield pk
            return
        self.deadline = time.monotonic() + MAX_SECONDS
        with self.phase("planning"):
            certain, possible = sql_bounds(self.tree, self.sql, self.evidence)
        if possible is False:
            return
        if isinstance(possible, Q):
            qs = qs.filter(possible)
        ordered = bool(qs.query.order_by)
        predicates = self.sql | self.evidence
        flags = {f"_abx_filter_{i}": term for i, term in enumerate(predicates)}
        qs = qs.annotate(**{name: Case(When(predicates[t], then=Value(True)), default=Value(False)) for name, t in flags.items()})
        # REST and exports preselect relations for serialization. Candidate
        # pages need their own narrower projection until membership is known.
        qs = (
            qs.select_related(None)
            .select_related("crawl__created_by")
            .only(
                "pk",
                "title",
                "url",
                "fs_version",
                "timestamp",
                "created_at",
                "bookmarked_at",
                "crawl__created_by__username",
            )
        )
        if not ordered:
            # Postings are a small, ranked starting set. A selective term can
            # have dozens of indexed hits while evaluating a broad SQL operand
            # against every snapshot (e.g. enumerating output filenames) is slow.
            # Check the original expression and scope, then continue the normal
            # plan for everything the index did not confirm.
            confirmed = set()
            words = tuple(dict.fromkeys(t for t in positive_terms(self.tree) if t.field == "word" and not has_uppercase(t.value)))
            quick, narrow = self.indexed_bounds
            if not isinstance(quick, Q) and isinstance(narrow, Q) and isinstance(certain, Q):
                # An indexed restriction can be necessary without being
                # sufficient (e.g. domain AND text). Check metadata for one
                # page of that small candidate stream before probing the index.
                quick = certain & Q(pk__in=self.witnesses(narrow)[:PAGE_SIZE])
            text = tuple(dict.fromkeys(t for t in positive_terms(self.tree) if t.field in {"word", "literal"}))
            # Publish field tiers in order. A fast full-text provider must not
            # occupy the first page before a stronger URL or title proof arrives.
            if text and isinstance(certain, Q):
                yield from self.ranked_metadata(text, certain, quick)
                qs = qs.exclude(certain)
            elif isinstance(quick, Q):
                for pk in self.indexed_witnesses(quick):
                    confirmed.add(pk)
                    yield pk
            for pk in self.indexed_hits(qs, flags, words):
                if pk not in confirmed:
                    confirmed.add(pk)
                    yield pk
            reverse_lookup = isinstance(self.tree, Term) and self.tree.field == "linkedfrom"
            if isinstance(certain, Q) and not text:
                # Each SQL witness is sufficient on its own. Do not repeat
                # expensive "possible" predicates, such as inspecting JSON keys.
                for pk in self.witnesses(certain).iterator(chunk_size=1):
                    if not self.active():
                        return
                    if pk not in confirmed:
                        if reverse_lookup:
                            confirmed.add(pk)
                        yield pk
                if reverse_lookup:
                    # Parsed destinations are exact saved URLs. Probe the URL
                    # index within scope without rerunning the source search for
                    # every file batch. target_batches already deduplicates URLs.
                    for targets in self.target_batches(self.tree, report_sources=True):
                        for batch in batched(targets, 256):
                            for pk in self.scope.filter(url__in=batch).order_by().values_list("pk", flat=True):
                                if pk not in confirmed:
                                    yield pk
                    self.partial |= not self.reverse[self.tree][1]
                    return
                qs = qs.exclude(certain)
            if words and set(words) == self.exhausted_words:
                # All SQL proofs were streamed above. In a positive expression
                # every further match must have a posting for at least one word.
                # The last contributing posting checks the full expression. A
                # negative or unenumerated operand still needs candidate checks.
                # Exhaustion does not certify that every snapshot was indexed.
                self.partial = True
                return
            if confirmed:
                qs = qs.exclude(pk__in=confirmed)
            # Revisit scoped postings whose remaining operands still need verification.
            if remaining := [pk for pk in self.hinted_ids if pk not in confirmed]:
                for batch in batched(remaining, PAGE_SIZE):
                    rows = {snap.pk: snap for snap in qs.filter(pk__in=batch).order_by()}
                    yield from self.page([rows[pk] for pk in batch if pk in rows], flags)
                qs = qs.exclude(pk__in=remaining)
        if ordered:
            if not qs.totally_ordered:
                qs = qs.order_by(*qs.query.order_by, "pk")
        else:
            qs = qs.order_by("pk")
        offset, cursor = 0, None
        while self.active():
            # Close the DB cursor before spawning a plugin or reading archive
            # storage. Keyset pagination is cheap when rank has no explicit sort.
            if ordered:
                page = list(qs[offset : offset + PAGE_SIZE])
            else:
                page = list((qs.filter(pk__gt=cursor) if cursor else qs)[:PAGE_SIZE])
            if not page:
                break
            # Unordered SQL proofs have already streamed. If file verification
            # is all that remains, stop paging the DB once its budget is spent.
            if (
                not ordered
                and self.scan_deadline is not None
                and (not self.scan_available() or (self.sonic_handshake is False and not self.fallback_candidates))
                and not any(term.field in {"linksto", "linkedfrom"} for term in self.terms)
            ):
                self.partial = True
                break
            # A short final DB page gives an exact denominator for free. Never
            # issue a COUNT or walk a second cursor just to animate the toolbar.
            if self.progress and len(page) < PAGE_SIZE:
                self.progress.total = offset + len(page)
            hits = self.page(page, flags, offset=offset)
            if ordered:
                matched = set(hits)
                yield from (snap.pk for snap in page if snap.pk in matched)
            else:
                yield from hits
            if self.progress:
                self.progress.checked = offset + len(page)
            if len(page) < PAGE_SIZE:
                break
            if self.streaming:
                self.link_cache.clear()
            cursor = page[-1].pk
            offset += PAGE_SIZE

    def witnesses(self, predicate, *, indexed=False):
        # No sort is requested in this lane. Let the DB walk its chosen index
        # and return the first row without building a temporary sort table.
        scope = self.index_probe_scope if indexed else self.scope
        return scope.filter(predicate).order_by().values_list("pk", flat=True)

    def indexed_witnesses(self, predicate):
        # SQLite can turn A OR B into a full snapshot scan even when both
        # alternatives have an index. Each outer disjunct is a sufficient
        # proof; keep AND and negated groups together. Seek direct keys before
        # materializing a subquery such as the set of matching hostnames.
        waves = [predicate]
        if predicate.connector == Q.OR and not predicate.negated:
            waves = [Q(child) for child in predicate.children]
            waves.sort(key=lambda wave: any(isinstance(value, QuerySet) for value in wave.flatten()))
        seen = set()
        # A second page can be requested while the remaining SQL is running.
        # Keep the exclusion list bounded for the exhaustive pass below.
        limit = 2 * PAGE_SIZE
        for wave in waves:
            if not self.active():
                return
            for pk in self.witnesses(wave, indexed=True)[:limit].iterator(chunk_size=1):
                if not self.active():
                    return
                if pk not in seen:
                    seen.add(pk)
                    yield pk
                    if len(seen) == limit:
                        return

    def ranked_metadata(self, terms, certain, quick):
        # These are disjoint lazy queries, without a database-wide score sort.
        # The first host/prefix seek can return a row while the later tiers have
        # yet to run. SQL membership and the original permission scope apply to
        # every tier, including ORs with another independently sufficient branch.
        remaining = self.scope.order_by()
        hosts = []
        for term in terms:
            # A single label appears unchanged in the stored reversed hostname.
            # Cross-label substrings need the display-order database function.
            if term.value.isascii() and term.value.isalnum():
                hosts.append(Q(reversed_domain__icontains=term.value))
            else:
                hosts.append(self.scope.model.objects.domain_rule_q("icontains", term.value))
        tiers = [Q(*hosts, _connector=Q.OR)]
        tiers.extend(Q(*(substring(field, t.value) for t in terms), _connector=Q.OR) for field in ("url", "title"))
        if isinstance(quick, Q):
            first = []
            for pk in self.indexed_witnesses(quick & tiers[0] & certain):
                first.append(pk)
                yield pk
            remaining = remaining.exclude(pk__in=first)
        for tier in tiers:
            for pk in remaining.filter(tier).filter(certain).values_list("pk", flat=True).iterator(chunk_size=1):
                if not self.active():
                    return
                yield pk
            remaining = remaining.exclude(tier)
        # Expensive metadata (tags and output paths) is checked last. Keyset
        # windows let sparse queries respond to client cancellation between reads.
        cursor = None
        scope_ids = self.scope.order_by("pk").values_list("pk", flat=True)
        while self.active():
            ids = list((scope_ids.filter(pk__gt=cursor) if cursor else scope_ids)[: PAGE_SIZE * 4])
            if not ids:
                return
            yield from list(remaining.filter(pk__in=ids).filter(certain).values_list("pk", flat=True))
            cursor = ids[-1]

    def indexed_hits(self, qs, flags, words):
        if not words or not self.backend or self.backend.config.search_scan:
            return
        # Spread a bounded set of early postings across Boolean alternatives;
        # a rare or empty first operand must not starve the next OR branch.
        # Full enumeration replaces the tail of the plan only when every
        # non-SQL operand is a positive index word. Negation and other
        # providers still need verification, so retain bounded hints there.
        exhaustive = (
            self.streaming
            and set(self.terms).difference(self.sql) == set(words)
            and not any(term in words for term in positive_terms(self.tree, negated=True))
        )
        for word in words:
            if not self.active():
                return
            yield from self.word_postings(qs, flags, word, 500 // len(words), exhaustive=exhaustive)

    def word_postings(self, qs, flags, word, limit, *, exhaustive):
        from abx_dl.execution import iter_plugin_command
        from archivebox.search.views import normalize_search_result_id

        command = get_plugin_catalog().command(self.backend.name, "search")
        if not command:
            return
        timeout = MAX_SECONDS if self.streaming else max(0.01, self.deadline - time.monotonic())
        # Some providers can answer a word in one cheap call inside the web
        # worker. Its positives need no second subprocess to verify the same
        # term. Legacy search commands supply hints for candidate verification.
        app = get_plugin_app(self.backend.name)
        pages = getattr(app, "search_word_pages", None) if exhaustive else None
        lookup = getattr(app, "search_word_hits", None)
        options = {"environ": self.env, "timeout": timeout}
        if self.sonic_handshake is False:
            return
        # Observe the existing first lookup, never a separate probe or a
        # substitute for complete pages. A subsequent error is not downtime.
        typed_name = "search_word_pages_with_availability" if pages else "search_word_hits_with_availability"
        if self.sonic_started is None and self.sonic_fallback and (observed := getattr(app, typed_name, None)):
            self.sonic_started = time.monotonic()
            options["observe"] = self.observe_sonic
            if pages:
                pages = observed
            else:
                lookup = observed
        postings = None
        if pages:
            page_iterator = pages(word.value, **options)
            if self.progress:
                page_iterator = self.progress.reading(page_iterator, "provider", self.backend.name, timeout=timeout, per_read=True)
            postings = chain.from_iterable(page_iterator)
        elif lookup:
            try:
                with self.phase("provider", self.backend.name, timeout=timeout):
                    postings = lookup(word.value, **options)
            except (ImportError, OSError, RuntimeError, ValueError) as err:
                logger.warning("In-process search unavailable: %s", type(err).__name__)
        confirmed_word = postings is not None
        if not self.active():
            return
        if postings is None:
            postings = iter_plugin_command(
                command,
                arguments={"query": word.value, "search_mode": "contents"},
                env=self.env,
                cwd=CONSTANTS.DATA_DIR,
                timeout=timeout,
                stop_event=self.stop_event,
            )
        if self.progress and not pages:
            postings = self.progress.reading(postings, "provider", self.backend.name, timeout=timeout)
        visited = set()
        try:
            bounded = iter(postings) if pages else islice(postings, limit)
            # Start verifying a handful before decoding all the output-file
            # metadata for a full index page. Command-only providers retain
            # larger batches to amortize their candidate subprocess startup.
            first = tuple(islice(bounded, 8)) if confirmed_word else ()
            batches = batched(bounded, PAGE_SIZE)
            if first:
                batches = chain((first,), batches)
            for batch in batches:
                ids = dict.fromkeys(pk for item in batch if (pk := normalize_search_result_id(item)) and pk not in visited)
                visited.update(ids)
                if confirmed_word:
                    yield from self.confirm_postings(ids, word, qs)
                else:
                    by_id = {row.pk.hex: row for row in qs.select_related(None).only("pk").filter(pk__in=ids)}
                    self.hinted_ids.update(dict.fromkeys(by_id[pk].pk for pk in ids if pk in by_id))
                    yield from self.page([by_id[pk] for pk in ids if pk in by_id], flags, index_only=True)
                if not self.active():
                    break
            else:
                if pages and self.sonic_handshake is not False:
                    self.exhausted_words.add(word)
        except (ImportError, OSError, ValueError, TypeError, KeyError, SubprocessError, RuntimeError) as err:
            stderr = getattr(err, "stderr", "") or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            logger.warning("Search postings unavailable: %s\n%s", err, stderr, exc_info=True)
        finally:
            if close := getattr(postings, "close", None):
                close()

    def confirm_postings(self, ids, word, qs):
        # A confirmed posting makes its word true in the whole expression.
        # Simplifying first avoids touching tags, output JSON, or the disk to
        # prove branches that can no longer affect this candidate's membership.
        groups = defaultdict(list)
        for pk in ids:
            known = tuple(term for term, hits in self.word_hits.items() if term != word and pk in hits)
            groups[known].append(pk)
        matches = {}
        for known, group in groups.items():
            expr = simplify(self.tree, dict.fromkeys((*known, word), True))
            certain, possible = (expr, expr) if isinstance(expr, bool) else sql_bounds(expr, self.sql, self.evidence)
            if possible is False:
                continue
            rows = qs.filter(pk__in=group).order_by()
            if isinstance(possible, Q):
                rows = rows.filter(possible)
            # The scope and any remaining SQL-only condition are checked in
            # one query. Unknowns can use this posting with a later index or
            # file result, but must not appear in the stream until confirmed.
            if certain == possible:
                proven = Value(True)
            elif isinstance(certain, Q):
                proven = Case(When(certain, then=Value(True)), default=Value(False))
            else:
                proven = Value(certain)
            for pk, hit in rows.values_list("pk", proven):
                self.hinted_ids[pk] = None
                self.word_hits[word].add(pk.hex)
                if hit:
                    matches[pk.hex] = pk
        yield from (matches[pk] for pk in ids if pk in matches)

    def page(self, page, flags, *, index_only=False, offset=None):
        pending, rows = {}, {}
        for snap in page:
            pk = snap.pk.hex
            values = {term: getattr(snap, name) for name, term in flags.items() if term in self.sql or getattr(snap, name)}
            values.update((term, True) for term, ids in self.word_hits.items() if pk in ids)
            expr = simplify(self.tree, values)
            if expr is True:
                yield snap.pk
            elif expr is not False:
                rows[pk], pending[pk] = snap, expr
        # Only the final candidate pass advances the counter. Index hints and
        # nested source lookups can revisit a row or use a different scope.
        unchecked = set(pending) if self.progress and offset is not None else None

        def checked(pk=None):
            if unchecked is not None:
                unchecked.discard(pk)
                self.progress.checked = offset + len(page) - len(unchecked)

        checked()
        if not pending or not self.active():
            self.partial |= bool(pending)
            return
        # Different OR branches can leave different expensive operands for
        # different rows. Only ask about predicates that could affect each row.
        groups = defaultdict(dict)
        for pk, expr in pending.items():
            required = tuple(dict.fromkeys(t for t in leaves(expr) if t.field in {"word", "literal"}))
            if required:
                groups[required][pk] = rows[pk]
        ranked = []
        for terms, batch in groups.items():
            backend = self.backend
            if self.sonic_handshake is False:
                self.partial = True
                if index_only or not self.fallback_candidates or not self.scan_available():
                    continue
                backend = self.sonic_fallback
                batch = dict(islice(batch.items(), self.fallback_candidates))
                self.fallback_candidates -= len(batch)
            if not backend:
                continue
            try:
                for pk, answers, scores in self.provider(backend, terms, batch):
                    if pk not in pending:
                        continue
                    checked(pk)
                    expr = simplify(pending[pk], answers)
                    if isinstance(expr, bool):
                        del pending[pk]
                        if expr:
                            ranked.append((sum(scores.get(t, 0) for t in answers if answers[t]), rows[pk].pk))
                    else:
                        pending[pk] = expr
            except (OSError, ValueError, TypeError, KeyError, SubprocessError, RuntimeError) as err:
                if self.streaming:
                    raise
                stderr = getattr(err, "stderr", "") or ""
                if isinstance(stderr, bytes):
                    stderr = stderr.decode(errors="replace")
                logger.warning("Search provider %s unavailable: %s\n%s", backend.name, err, stderr, exc_info=True)
        # Reorder only confirmed hits in this index page. Never hold file
        # hits for ranking or move a result the browser already received.
        yield from (pk for _, pk in sorted(ranked, key=lambda match: -match[0]))
        if index_only:
            # Unknowns remain eligible for verification in the regular
            # page pass. Do not start disk I/O while delivering index hits.
            return
        outgoing = [rows[pk] for pk, expr in pending.items() if any(term.field == "linksto" for term in leaves(expr))]
        for snapshot, urls, done in self.link_rows(outgoing):
            pk = snapshot.pk.hex
            checked(pk)
            expr = pending[pk]
            answers = {}
            for term in dict.fromkeys(leaves(expr)):
                if term.field == "linksto":
                    pattern = literal_pattern(term.value)
                    hit = any(pattern.search(url) for url in urls)
                    if hit or done:
                        answers[term] = hit
            expr = simplify(expr, answers)
            if isinstance(expr, bool):
                del pending[pk]
                if expr:
                    yield snapshot.pk
            else:
                pending[pk] = expr
        for pk, expr in list(pending.items()):
            for term in tuple(dict.fromkeys(leaves(expr))):
                if term.field == "linkedfrom":
                    if term not in self.reverse:
                        for _ in self.target_batches(term):
                            pass
                    urls, done = self.reverse[term]
                    hit = rows[pk].url in urls
                else:
                    continue
                if hit or done:
                    expr = simplify(expr, {term: hit})
                if isinstance(expr, bool):
                    break
            if expr is True:
                yield rows[pk].pk
            if isinstance(expr, bool):
                del pending[pk]
            else:
                pending[pk] = expr
        self.partial |= bool(pending)
