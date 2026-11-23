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
from itertools import batched, islice
from pathlib import Path
from subprocess import SubprocessError

from django.db.models import Case, Q, Value, When

from archivebox.config.common import get_config
from archivebox.config.constants import CONSTANTS
from archivebox.plugins.discovery import get_plugin_catalog
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


class SnapshotSearch:
    def __init__(self, scope, query, *, config=None, stop_event=None, rules=None, stack=(), public=False, streaming=False):
        self.scope = scope
        self.tree = parse(query)
        self.terms = tuple(dict.fromkeys(leaves(self.tree)))
        if rules is None and any("__" in t.field for t in self.terms):
            from archivebox.core.smart_folders import RuleQuery

            rules = RuleQuery()
        self.sql = {t: q for t in self.terms if (q := sql_leaf(t, scope.db, rules=rules, stack=stack, public=public)) is not None}
        self.text = {t: text_metadata(t, public=public) for t in self.terms if t.field in {"word", "literal"}}
        self.config = config
        self.streaming = streaming
        self.stop_event = stop_event
        self.partial = False
        self.usage = Counter()
        self.read_ids = set()
        self.link_cache = {}
        self.reverse = {}
        self.legacy_hits = {}
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
        if len(self.sql) == len(self.terms):
            return self.scope.filter(sql_bounds(self.tree, self.sql)[1])
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

    def admit(self, pk):
        if self.streaming:
            return True
        if pk not in self.read_ids and len(self.read_ids) >= MAX_SNAPSHOTS:
            return False
        self.read_ids.add(pk)
        return all(self.usage[name] < maximum for name, maximum in DISK_LIMITS.items())

    @cached_property
    def link_paths(self):
        return [Path(p.name, p.manifest["outlinks_path"]) for p in get_plugin_catalog().values() if p.manifest.get("outlinks_path")]

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

    def links(self, snapshot):
        if snapshot.pk in self.link_cache:
            return self.link_cache[snapshot.pk]
        if not self.active() or not self.admit(snapshot.pk) or not self.link_paths:
            return set(), False
        root = CONSTANTS.ARCHIVE_DIR
        # Use the stored layout here; guessing alternative paths by probing a
        # remote mount on the request thread would bypass the read deadline.
        folder = snapshot.get_storage_path_for_version(snapshot.fs_version)
        if not folder.is_relative_to(root) or ".." in folder.parts:
            return set(), False
        payload = {
            "root": str(root),
            "relatives": [str(folder.relative_to(root) / p) for p in self.link_paths],
            "byte_limit": DISK_LIMITS["bytes"] - self.usage["bytes"],
            "file_limit": DISK_LIMITS["files"] - self.usage["files"],
        }
        if self.streaming:
            # A connected search reads beyond the preview limits. Keep the
            # helper cancellable even if the mounted archive stops responding.
            from abx_dl.models import PluginCommand

            reader = Path(__file__).with_name("outlinks.py")
            command = PluginCommand(name="outlinks", plugin_name="archivebox", path=Path(sys.executable), args=["-I", str(reader)])
            records = self.command_records(command, {**payload, "streaming": True})
            urls, complete = set(), False
            try:
                for item in records:
                    if isinstance(item, str):
                        urls.add(item)
                    else:
                        complete = item["complete"]
            finally:
                records.close()
            self.link_cache[snapshot.pk] = urls, complete
            return urls, complete
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

    def sources(self, term):
        qs = (
            self.scope.filter(substring("url", term.value))
            .filter(Q(url__istartswith="http://") | Q(url__istartswith="https://"))
            .select_related("crawl__created_by")
            .order_by("pk")
        )
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
        for index, snapshot in enumerate(self.sources(term)):
            if (not self.streaming and index == MAX_SNAPSHOTS) or not self.active():
                complete = False
                break
            links, done = self.links(snapshot)
            if self.streaming:
                self.link_cache.pop(snapshot.pk, None)
            complete &= done
            new = links - seen
            seen.update(new)
            if new:
                yield new
        self.reverse[term] = seen, complete

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
        iterator = self.command_records(command, payload, env=self.env)
        try:
            for record in iterator:
                pk = str(record["id"]).replace("-", "")
                if pk not in admitted:
                    continue
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
        if isinstance(self.tree, Term) and self.tree.field == "linkedfrom" and not qs.query.order_by:
            for targets in self.target_batches(self.tree):
                for batch in batched(targets, 256):
                    yield from qs.filter(url__in=batch).values_list("pk", flat=True)
            self.partial |= not self.reverse[self.tree][1]
            return
        certain, possible = sql_bounds(self.tree, self.sql, self.text)
        if possible is False:
            return
        if isinstance(possible, Q):
            qs = qs.filter(possible)
        ordered = bool(qs.query.order_by)
        if not ordered and isinstance(certain, Q):
            # Confirmed SQL results can stream immediately. Exclude that same
            # predicate below so those snapshots never reach an external reader.
            for pk in qs.filter(certain).order_by("pk").values_list("pk", flat=True).iterator(chunk_size=PAGE_SIZE):
                if self.stop_event and self.stop_event.is_set():
                    return
                yield pk
            qs = qs.exclude(certain)
        flags = {f"_abx_filter_{i}": term for i, term in enumerate((*self.sql, *self.text))}
        predicates = self.sql | self.text
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
        if (
            not ordered
            and isinstance(self.tree, Term)
            and self.tree.field == "word"
            and not has_uppercase(self.tree.value)
            and self.backend
            and not self.backend.config.search_scan
        ):
            # Query existing postings before arbitrary UUID pages. Treat these as
            # hints: the scoped command verifies each candidate and supplies scores.
            from archivebox.search.views import normalize_search_result_id
            from abx_dl.execution import iter_plugin_command

            command = get_plugin_catalog().command(self.backend.name, "search")
            if not qs.exists():
                return
            if command and self.active():
                postings = iter_plugin_command(
                    command,
                    arguments={"query": self.tree.value, "search_mode": "contents"},
                    env=self.env,
                    cwd=CONSTANTS.DATA_DIR,
                    timeout=MAX_SECONDS if self.streaming else max(0.01, self.deadline - time.monotonic()),
                    stop_event=self.stop_event,
                )
                visited = set()
                try:
                    for batch in batched(islice(postings, 500), PAGE_SIZE):
                        ids = [pk for item in batch if (pk := normalize_search_result_id(item)) and pk not in visited]
                        by_id = {row.pk.hex: row for row in qs.filter(pk__in=ids)}
                        page = [by_id[pk] for pk in dict.fromkeys(ids) if pk in by_id]
                        visited.update(by_id)
                        if page:
                            yield from self.page(page, flags)
                        if not self.active():
                            break
                except (OSError, ValueError, TypeError, KeyError, SubprocessError, RuntimeError) as err:
                    logger.warning("Search postings unavailable: %s", type(err).__name__)
                finally:
                    postings.close()
                if visited:
                    qs = qs.exclude(pk__in=visited)
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

    def page(self, page, flags):
        pending, rows = {}, {}
        for snap in page:
            pk = snap.pk.hex
            values = {term: getattr(snap, name) for name, term in flags.items() if term in self.sql or getattr(snap, name)}
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
                    logger.warning("Search provider %s unavailable: %s", backend.name, type(err).__name__)
            # Reorder only confirmed hits in this index page. Never hold file
            # hits for ranking or move a result the browser already received.
            yield from (pk for _, pk in sorted(ranked, key=lambda match: -match[0]))
            if not disk:
                for pk, expr in list(pending.items()):
                    for term in tuple(dict.fromkeys(leaves(expr))):
                        if term.field == "linkedfrom":
                            if term not in self.reverse:
                                for _ in self.target_batches(term):
                                    pass
                            urls, done = self.reverse[term]
                            hit = rows[pk].url in urls
                        elif term.field == "linksto":
                            urls, done = self.links(rows[pk])
                            hit = any(literal_pattern(term.value).search(url) for url in urls)
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
