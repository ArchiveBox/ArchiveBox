"""Plan one search against an already permission-filtered Snapshot queryset."""

import json
import logging
import math
import subprocess
import sys
import time
import threading
from collections import Counter, defaultdict
from functools import cached_property
from itertools import batched, chain, islice
from pathlib import Path
from queue import Empty, SimpleQueue
from subprocess import SubprocessError

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Case, Q, Value, When

from archivebox.config.common import get_config
from archivebox.config.constants import CONSTANTS
from archivebox.plugins.discovery import get_plugin_app, get_plugin_catalog
from archivebox.search.backends import get_available_backends, get_backend, search_backend_command_env
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
    text_metadata,
    url_substring_hint,
)

logger = logging.getLogger(__name__)
PAGE_SIZE = 64
# External work is shared by every Boolean branch. Metadata-only queries remain
# ordinary lazy Django queries and never consume this file budget.
DISK_LIMITS = {"files": 96, "entries": 512, "bytes": 4 << 20}
MAX_SNAPSHOTS = 12
MAX_SECONDS = 8.0
# Only external work competes for these slots. A missing or slow mounted drive
# must not block ordinary metadata searches or multiply disk load per browser.
EXTERNAL_SLOTS = threading.BoundedSemaphore(2)
STALL_SECONDS = 30.0
# Only the first screen needs speculative concurrency. More simultaneous
# viewers still execute the same complete plan without additional threads.
FIRST_PAGE_SLOTS = threading.BoundedSemaphore(2)


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
            if not (field.primary_key or field.unique or field.db_index):
                return False
        else:
            return False
    return bool(predicate.children)


def positive_words(node, negated=False):
    if isinstance(node, Term):
        if not negated and node.field == "word" and not has_uppercase(node.value):
            yield node
        return
    for child in node.args:
        yield from positive_words(child, negated != (node.op == "not"))


def sql_snapshot_search(scope, query, *, public=False):
    """Return a lazy metadata queryset, or defer external work and syntax errors to the stream."""
    try:
        return SnapshotSearch(scope, query, public=public).sql_queryset()
    except (ValueError, ValidationError):
        return None


class SnapshotSearch:
    def __init__(self, scope, query, *, config=None, stop_event=None, rules=None, stack=(), public=False, streaming=False):
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
            if term.field not in {"word", "literal", "linkedfrom", "linksto"}:
                continue
            hint = url_substring_hint(term.value, scope.db)
            if hint is not None:
                self.url_hints[term] = hint
            if term.field in {"word", "literal"}:
                if hint is not None:
                    self.indexed_evidence[term] = hint & substring("url", term.value)
                continue
            endpoints = self.link_endpoints(term)
            if hint is not None:
                self.indexed_evidence[term] = self.recorded_links(term, endpoints.filter(hint))
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
        self.read_ids = set()
        self.link_cache = {}
        self.reverse = {}
        self.legacy_hits = {}
        self.word_hits = defaultdict(set)
        self.hinted_ids = set()
        self.deadline = None

    @cached_property
    def env(self):
        self.config = self.config or get_config()
        return search_backend_command_env(config=self.config)

    @cached_property
    def backend(self):
        self.config = self.config or get_config()
        return get_backend(config=self.config) if get_available_backends() else None

    @cached_property
    def scanner(self):
        if self.backend and self.backend.config.search_scan and get_plugin_catalog().command(self.backend.name, "search_candidates"):
            return self.backend
        return next(
            (
                p
                for p in get_available_backends().values()
                if p.config.search_scan and get_plugin_catalog().command(p.name, "search_candidates")
            ),
            None,
        )

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

    def sql_queryset(self):
        if len(self.sql) == len(self.terms):
            return self.scope.filter(sql_bounds(self.tree, self.sql)[1])
        return None

    def admit(self, pk):
        if self.streaming:
            return True
        if pk not in self.read_ids and len(self.read_ids) >= MAX_SNAPSHOTS:
            return False
        self.read_ids.add(pk)
        return all(self.usage[name] < maximum for name, maximum in DISK_LIMITS.items())

    def command_records(self, command, payload, *, env=None):
        from abx_dl.execution import iter_plugin_command

        if not self.streaming:
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

        while not EXTERNAL_SLOTS.acquire(timeout=0.1):
            if not self.active():
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
            lines = iter_plugin_command(
                command,
                stdin=[json.dumps(payload)],
                cwd=CONSTANTS.DATA_DIR,
                env=env,
                stop_event=ScanCancellation(),
                timeout=None,
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
            records = self.command_records(command, {"root": str(root), "snapshots": paths})
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
        if not self.admit(snapshot.pk):
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
        return Q(pk__in=endpoints.exclude(parent_snapshot_id=None).values("parent_snapshot_id"))

    def link_endpoints(self, term):
        return self.scope.order_by().filter(substring("url", term.value), Q(url__istartswith="http://") | Q(url__istartswith="https://"))

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
        if not self.streaming:
            yield from qs[: MAX_SNAPSHOTS + 1]
            return
        cursor = None
        while self.active():
            page = list((qs.filter(pk__gt=cursor) if cursor else qs)[:PAGE_SIZE])
            if not page:
                return
            yield from page
            cursor = page[-1].pk

    def target_batches(self, term):
        seen, complete = set(), True
        sources = self.sources(term)
        if not self.streaming:
            bounded = list(sources)
            complete = len(bounded) <= MAX_SNAPSHOTS
            sources = bounded[:MAX_SNAPSHOTS]
        for _, links, done in self.link_rows(sources):
            complete &= done
            new = links - seen
            seen.update(new)
            if new:
                yield new
        self.reverse[term] = seen, complete and self.active()

    def provider(self, backend, terms, rows, *, disk=False):
        """Yield evidence from registered commands. An omitted answer is unknown."""
        from abx_dl.execution import iter_plugin_command

        if not backend or not rows or not terms or not self.active():
            return
        command = get_plugin_catalog().command(backend.name, "search_candidates")
        if not command:
            # Older third-party indexes still supply positive evidence via
            # their registered search command. A limited posting list cannot prove NOT.
            command = get_plugin_catalog().command(backend.name, "search")
            for term in terms:
                if disk or not command or term.field != "word" or has_uppercase(term.value):
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
            if disk and not self.admit(snap.pk):
                continue
            candidate = {"id": pk}
            if disk:
                path = snap.get_storage_path_for_version(snap.fs_version)
                if not path.is_relative_to(CONSTANTS.ARCHIVE_DIR) or ".." in path.parts:
                    continue
                candidate["path"] = str(path)
            candidates.append(candidate)
        if not candidates:
            return
        admitted = {candidate["id"] for candidate in candidates}
        payload = {
            "streaming": self.streaming,
            "terms": [{"key": k, "mode": t.field, "value": t.value} for k, t in keys.items()],
            "candidates": candidates,
            "limits": {
                **{k: v if self.streaming else max(0, v - self.usage[k]) for k, v in DISK_LIMITS.items()},
                "seconds": MAX_SECONDS if self.streaming else max(0.01, self.deadline - time.monotonic()),
                "per_file": 512 << 10,
            },
        }
        if disk:
            payload["archive_root"] = str(CONSTANTS.ARCHIVE_DIR)
            self.archive_batch = (0, len(admitted))
            checked = set()
        iterator = self.command_records(command, payload, env=self.env)
        try:
            for record in iterator:
                pk = str(record["id"]).replace("-", "")
                if pk not in admitted:
                    continue
                if disk:
                    checked.add(pk)
                    self.archive_batch = (len(checked), len(admitted))
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

    def stream(self):
        qs = self.scope
        if len(self.sql) == len(self.terms):
            yield from self.queryset().values_list("pk", flat=True).iterator(chunk_size=PAGE_SIZE)
            return
        self.deadline = time.monotonic() + MAX_SECONDS
        certain, possible = sql_bounds(self.tree, self.sql, self.evidence)
        if possible is False:
            return
        if isinstance(possible, Q):
            qs = qs.filter(possible)
        ordered = bool(qs.query.order_by)
        flags = {f"_abx_filter_{i}": term for i, term in enumerate((*self.sql, *self.evidence))}
        predicates = self.sql | self.evidence
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
            words = tuple(dict.fromkeys(positive_words(self.tree)))
            quick, narrow = sql_bounds(
                self.tree,
                {term: q for term, q in self.sql.items() if indexed_predicate(self.scope.model, q)},
                self.indexed_evidence,
            )
            if not isinstance(quick, Q) and isinstance(narrow, Q) and isinstance(certain, Q):
                # An indexed restriction can be necessary without being
                # sufficient (e.g. domain AND text). Check metadata for one
                # page of that small candidate stream before probing the index.
                quick = certain & Q(pk__in=self.witnesses(narrow)[:PAGE_SIZE])
            race = self.streaming and words and isinstance(certain, Q) and not connections[self.scope.db].in_atomic_block
            witness_pages = self.witness_pages(certain, narrow) if race else None
            if race and FIRST_PAGE_SLOTS.acquire(blocking=False):
                yield from self.first_screen(qs, flags, words, quick, witness_pages, confirmed)
                # A disconnected stream can leave a worker finishing its last
                # bounded SELECT. Only resume its iterator after normal completion.
                if not self.active():
                    return
            else:
                if isinstance(quick, Q):
                    for pk in self.witnesses(quick)[:PAGE_SIZE].iterator(chunk_size=1):
                        confirmed.add(pk)
                        yield pk
                if witness_pages is not None:
                    # Busy workers should not force a collection-wide scan
                    # ahead of a responsive index. Try one bounded DB page.
                    for pk in next(witness_pages, ()):
                        if pk not in confirmed:
                            confirmed.add(pk)
                            yield pk
                for pk in self.indexed_hits(qs, flags, words):
                    if pk not in confirmed:
                        confirmed.add(pk)
                        yield pk
            reverse_lookup = isinstance(self.tree, Term) and self.tree.field == "linkedfrom"
            if isinstance(certain, Q):
                # Each SQL witness is sufficient on its own. Do not repeat
                # expensive "possible" predicates, such as inspecting JSON keys.
                witnesses = (
                    chain.from_iterable(witness_pages) if witness_pages is not None else self.witnesses(certain).iterator(chunk_size=1)
                )
                for pk in witnesses:
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
                    for targets in self.target_batches(self.tree):
                        for batch in batched(targets, 256):
                            for pk in self.scope.filter(url__in=batch).order_by().values_list("pk", flat=True):
                                if pk not in confirmed:
                                    yield pk
                    self.partial |= not self.reverse[self.tree][1]
                    return
                qs = qs.exclude(certain)
            if confirmed:
                qs = qs.exclude(pk__in=confirmed)
            # Some index candidates still need another source (word AND deep,
            # for example). Visit those before unrelated arbitrary UUID pages.
            if remaining := self.hinted_ids - confirmed:
                for batch in batched(remaining, PAGE_SIZE):
                    yield from self.page(list(qs.filter(pk__in=batch)), flags)
                qs = qs.exclude(pk__in=remaining)
        if ordered:
            if not qs.totally_ordered:
                qs = qs.order_by(*qs.query.order_by, "pk")
        else:
            qs = qs.order_by("pk")
        offset, cursor = 0, None
        external = set(self.terms) - self.sql.keys()
        file_only = all(t.field in {"deep", "linkedfrom", "linksto"} for t in external)
        while self.active():
            # Close the DB cursor before spawning a plugin or reading archive
            # storage. Keyset pagination is cheap when rank has no explicit sort.
            if ordered:
                page = list(qs[offset : offset + PAGE_SIZE])
            else:
                page = list((qs.filter(pk__gt=cursor) if cursor else qs)[:PAGE_SIZE])
            if not page:
                break
            hits = self.page(page, flags)
            if ordered:
                matched = set(hits)
                yield from (snap.pk for snap in page if snap.pk in matched)
            else:
                yield from hits
            if len(page) < PAGE_SIZE:
                break
            if not ordered and file_only and len(self.read_ids) == MAX_SNAPSHOTS and not any(t.field == "linkedfrom" for t in external):
                # Remaining disk-only rows cannot be admitted. All certain SQL
                # branches were already delivered by the initial metadata wave.
                self.partial = True
                break
            if self.streaming:
                self.link_cache.clear()
            cursor = page[-1].pk
            offset += PAGE_SIZE

    def witnesses(self, predicate):
        # No sort is requested in this lane. Let the DB walk its chosen index
        # and return the first row without building a temporary sort table.
        return self.scope.filter(predicate).order_by().values_list("pk", flat=True)

    def witness_pages(self, certain, narrow):
        # A sparse WHERE ... LIMIT 64 can keep the DB busy for seconds after
        # a tab disconnects, starving the next search. Keyset windows give
        # cancellation a turn even when the database finds *zero* matches.
        candidates = self.scope.order_by("pk").values_list("pk", flat=True)
        if isinstance(narrow, Q):
            candidates = candidates.filter(narrow)
        size = PAGE_SIZE
        cursor = None
        while self.active():
            ids = list((candidates.filter(pk__gt=cursor) if cursor else candidates)[:size])
            if not ids:
                return
            yield list(self.witnesses(certain).filter(pk__in=ids))
            if len(ids) < size:
                return
            cursor = ids[-1]
            size = PAGE_SIZE * 4

    def first_screen(self, qs, flags, words, quick, witness_pages, confirmed):
        """Publish independent proofs as they arrive; disk fallback never runs in these lanes."""
        # At most two SQL prefixes and 500 postings can be enqueued. A
        # bounded blocking put here could hold a database cursor behind HTTP.
        events = SimpleQueue()
        closed = threading.Event()
        index_ready = threading.Event()
        quick_ready = threading.Event()

        def sql_hits():
            try:
                if isinstance(quick, Q):
                    yield from self.witnesses(quick)[:PAGE_SIZE].iterator(chunk_size=1)
            finally:
                quick_ready.set()
            # A broad SQL scan can monopolize I/O. Give a responsive index
            # first chance, but a stalled one cannot hold back database matches.
            index_ready.wait(0.075)
            count = 0
            while not closed.is_set() and self.active() and count < PAGE_SIZE:
                page = next(witness_pages, None)
                if page is None:
                    break
                yield from page
                count += len(page)
                if index_ready.is_set():
                    break

        def index_hits():
            quick_ready.wait(0.025)
            try:
                yield from self.indexed_hits(qs, flags, words)
            finally:
                index_ready.set()

        # Workers use separate Django connections. Do not borrow a transaction
        # or leave a cursor open while a consumer waits on a plugin or a socket.
        unfinished = 2
        finish_lock = threading.Lock()

        def finished():
            nonlocal unfinished
            with finish_lock:
                unfinished -= 1
                if not unfinished:
                    FIRST_PAGE_SLOTS.release()

        def produce(source):
            try:
                close_old_connections()
                for pk in source():
                    if closed.is_set() or not self.active():
                        break
                    events.put(pk)
            except Exception as exc:
                events.put(exc)
            finally:
                connections.close_all()
                events.put(None)
                finished()

        started = 0
        try:
            for source in (sql_hits, index_hits):
                threading.Thread(target=produce, args=(source,), name="search-first-page", daemon=True).start()
                started += 1
            ended = 0
            while ended < 2 and self.active():
                try:
                    item = events.get(timeout=0.05)
                except Empty:
                    continue
                if isinstance(item, Exception):
                    raise item
                if item is None:
                    ended += 1
                elif item not in confirmed:
                    confirmed.add(item)
                    yield item
        finally:
            closed.set()
            # A worker that could not start cannot release its share.
            for _ in range(2 - started):
                finished()

    def indexed_hits(self, qs, flags, words):
        if not words or not self.backend or self.backend.config.search_scan:
            return
        # Spread a bounded set of early postings across Boolean alternatives;
        # a rare or empty first operand must not starve the next OR branch.
        for word in words:
            if not self.active():
                return
            yield from self.word_postings(qs, flags, word, 500 // len(words))

    def word_postings(self, qs, flags, word, limit):
        from abx_dl.execution import iter_plugin_command
        from archivebox.search.views import normalize_search_result_id

        command = get_plugin_catalog().command(self.backend.name, "search")
        if not command:
            return
        timeout = MAX_SECONDS if self.streaming else max(0.01, self.deadline - time.monotonic())
        # Some providers can answer a word in one cheap call inside the web
        # worker. Its positives need no second subprocess to verify the same
        # term. Legacy search commands supply hints for candidate verification.
        lookup = getattr(get_plugin_app(self.backend.name), "search_word_hits", None)
        postings = None
        if lookup:
            try:
                postings = lookup(word.value, environ=self.env, timeout=timeout)
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
        visited = set()
        try:
            bounded = islice(postings, limit)
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
                    yield from self.confirm_postings(ids, word)
                else:
                    by_id = {row.pk.hex: row for row in qs.select_related(None).only("pk").filter(pk__in=ids)}
                    self.hinted_ids.update(row.pk for row in by_id.values())
                    yield from self.page([by_id[pk] for pk in ids if pk in by_id], flags, index_only=True)
                if not self.active():
                    break
        except (ImportError, OSError, ValueError, TypeError, KeyError, SubprocessError, RuntimeError) as err:
            stderr = getattr(err, "stderr", "") or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            logger.warning("Search postings unavailable: %s\n%s", err, stderr, exc_info=True)
        finally:
            if close := getattr(postings, "close", None):
                close()

    def confirm_postings(self, ids, word):
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
            rows = self.scope.filter(pk__in=group).order_by()
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
                self.hinted_ids.add(pk)
                self.word_hits[word].add(pk.hex)
                if hit:
                    matches[pk.hex] = pk
        yield from (matches[pk] for pk in ids if pk in matches)

    def page(self, page, flags, *, index_only=False):
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
        for disk in (False, True):
            if not pending or not self.active():
                break
            fields = {"word", "literal", "deep"} if disk else {"word", "literal"}
            if disk and self.backend and not (self.backend.config.search_scan or self.backend.config.search_fallback):
                fields = {"deep"}
            # Different OR branches can leave different expensive operands for
            # different rows. Only ask about predicates that could affect each row.
            groups = defaultdict(dict)
            for pk, expr in pending.items():
                required = tuple(dict.fromkeys(t for t in leaves(expr) if t.field in fields))
                if required:
                    groups[required][pk] = rows[pk]
            ranked = []
            for terms, batch in groups.items():
                backend = self.scanner if disk else self.backend
                if not backend or (not disk and backend.config.search_scan):
                    continue
                try:
                    for pk, answers, scores in self.provider(backend, terms, batch, disk=disk):
                        if pk not in pending:
                            continue
                        if disk and (not self.backend or not self.backend.config.search_scan):
                            # A negative in a fallback file scan cannot disprove
                            # a word in a different provider's indexed document.
                            answers = {t: value for t, value in answers.items() if t.field == "deep" or value}
                        expr = simplify(pending[pk], answers)
                        if isinstance(expr, bool):
                            del pending[pk]
                            if expr and disk:
                                yield rows[pk].pk
                            elif expr:
                                ranked.append((sum(scores.get(t, 0) for t in answers if answers[t]), rows[pk].pk))
                        else:
                            pending[pk] = expr
                except (OSError, ValueError, TypeError, KeyError, SubprocessError, RuntimeError) as err:
                    if self.streaming and (disk or not backend.config.search_fallback):
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
            if not disk:
                outgoing = [rows[pk] for pk, expr in pending.items() if any(term.field == "linksto" for term in leaves(expr))]
                for snapshot, urls, done in self.link_rows(outgoing):
                    pk = snapshot.pk.hex
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
        if not index_only:
            self.partial |= bool(pending)
