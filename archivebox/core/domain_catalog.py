"""Rebuildable domain listings derived from snapshot URLs outside the main database."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sqlite3
from threading import Lock, Thread
from time import monotonic, time
from urllib.parse import urlsplit

from django.db import close_old_connections, connection, connections

from archivebox.config import CONSTANTS
from archivebox.core.domain_index import group_host
from archivebox.core.permissions import PERMISSIONS_PUBLIC

logger = logging.getLogger(__name__)
_BATCH_SIZE = 1000
_SEARCH_PROBE_SIZE = 2000
# Published files are snapshots of a complete pass. Large collections can show
# stale counts or omit newly archived domains until a later request triggers a
# refresh. Public rendering checks the chosen witness against live permissions.
_REFRESH_INTERVAL = 5 * 60
_REFRESH_RETRY = 15
_REFRESH_FAILURE_RETRY = 60
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_DATE_FIELDS = {"oldest_at", "newest_at"}
_CAPTURE_IDS = ("root_id", "public_id", "newest_id", "oldest_id")
_ORDER_FIELDS = {
    "domain": "domain",
    "count": "snapshot_count",
    "size": "total_size",
    "personas": "persona_count",
    "oldest": "oldest_at",
    "newest": "newest_at",
}
_refresh_lock = Lock()
_refresh_path: Path | None = None
_next_refresh = 0.0


def order_field(ordering: str) -> str:
    return _ORDER_FIELDS.get(ordering.lstrip("-"), "domain")


def _snapshots():
    from archivebox.core.models import Snapshot

    return Snapshot.objects.order_by("pk").values_list("pk", "url", "created_at", "output_size", "crawl__persona_id", "permissions")


def _snapshot_batches(snapshots):
    last = None
    while True:
        page = list((snapshots.filter(pk__gt=last) if last is not None else snapshots)[:_BATCH_SIZE])
        if not page:
            return
        yield page
        if len(page) < _BATCH_SIZE:
            return
        last = page[-1][0]


def _date_micros(date: datetime) -> int:
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    delta = date - _UTC_EPOCH
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def _capture_rows(snapshots):
    for snapshot_id, url, created, size, persona, permissions in snapshots:
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
        except ValueError:
            continue
        if parsed.scheme not in {"http", "https"} or not host:
            continue
        domain, scope = group_host(host)
        if not domain:
            continue
        depth = max(0, parsed.path.count("/") - int(parsed.path.endswith("/")))
        yield (
            snapshot_id.bytes,
            domain,
            scope,
            _date_micros(created),
            size or 0,
            persona.bytes if persona is not None else None,
            depth,
            permissions == PERMISSIONS_PUBLIC,
        )


def _populate(database: sqlite3.Connection, batches) -> None:
    # Temporary capture rows provide an external sort and exact aggregates without
    # keeping a growing dictionary of domains or personas in process memory.
    database.executescript(
        """
        PRAGMA temp_store=FILE;
        PRAGMA temp.cache_size=-8192;
        CREATE TEMP TABLE captures (
            id BLOB NOT NULL,
            domain TEXT NOT NULL,
            scope TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            size INTEGER NOT NULL,
            persona BLOB,
            depth INTEGER NOT NULL,
            public INTEGER NOT NULL
        );
        CREATE TABLE domains (
            domain TEXT NOT NULL PRIMARY KEY,
            scope TEXT NOT NULL,
            root_id BLOB NOT NULL,
            public_id BLOB,
            newest_id BLOB NOT NULL,
            oldest_id BLOB NOT NULL,
            oldest_at INTEGER NOT NULL,
            newest_at INTEGER NOT NULL,
            snapshot_count INTEGER NOT NULL,
            total_size INTEGER NOT NULL,
            persona_count INTEGER NOT NULL
        );
        """,
    )
    short_terms = set()
    for batch in batches:
        captures = list(_capture_rows(batch))
        for domain in {row[1] for row in captures}:
            short_terms.update(domain)
            short_terms.update(domain[index : index + 2] for index in range(len(domain) - 1))
        database.executemany("INSERT INTO captures VALUES (?, ?, ?, ?, ?, ?, ?, ?)", captures)
    database.execute("CREATE TABLE short_terms (term TEXT PRIMARY KEY) WITHOUT ROWID")
    database.executemany("INSERT INTO short_terms VALUES (?)", ((term,) for term in short_terms))
    database.executescript(
        """
        CREATE INDEX captures_dates ON captures(domain, created_at, id);
        CREATE INDEX captures_roots ON captures(domain, depth, created_at DESC, id DESC);
        CREATE INDEX captures_public ON captures(domain, depth, created_at DESC, id DESC) WHERE public=1;
        INSERT INTO domains
            SELECT c.domain, min(c.scope),
                (SELECT id FROM captures WHERE domain=c.domain ORDER BY depth, created_at DESC, id DESC LIMIT 1),
                (SELECT id FROM captures WHERE domain=c.domain AND public=1 ORDER BY depth, created_at DESC, id DESC LIMIT 1),
                (SELECT id FROM captures WHERE domain=c.domain ORDER BY created_at DESC, id DESC LIMIT 1),
                (SELECT id FROM captures WHERE domain=c.domain ORDER BY created_at, id LIMIT 1),
                min(c.created_at), max(c.created_at), count(*), sum(c.size), count(DISTINCT c.persona)
            FROM captures c GROUP BY c.domain;
        DROP TABLE captures;
        CREATE INDEX public_domains ON domains(domain) WHERE public_id IS NOT NULL;
        CREATE INDEX domains_count ON domains(snapshot_count, domain);
        CREATE INDEX domains_size ON domains(total_size, domain);
        CREATE INDEX domains_personas ON domains(persona_count, domain);
        CREATE INDEX domains_oldest ON domains(oldest_at, domain);
        CREATE INDEX domains_newest ON domains(newest_at, domain);
        """,
    )


def _create_search_index(database: sqlite3.Connection) -> None:
    # FTS5 isn't enabled in every SQLite distribution. Ordered scans remain
    # available for those installations and for literal terms under three chars.
    try:
        database.execute(
            "CREATE VIRTUAL TABLE domain_search USING fts5(domain, content='domains', content_rowid='rowid', tokenize='trigram')",
        )
    except sqlite3.OperationalError as error:
        if "no such module" not in str(error) and "no such tokenizer" not in str(error):
            raise
        return
    database.execute("INSERT INTO domain_search(domain_search) VALUES ('rebuild')")


def _page(database, *, query, ordering, after, backwards, public, limit):
    if 0 < len(query) < 3 and not database.execute("SELECT 1 FROM short_terms WHERE term=?", (query,)).fetchone():
        return []
    field = order_field(ordering)
    reverse = ordering.startswith("-") != backwards
    direction = "DESC" if reverse else "ASC"
    comparison = "<" if reverse else ">"
    conditions = []
    parameters = []
    if public:
        conditions.append("public_id IS NOT NULL")
    sort = f"domain {direction}"
    if field != "domain":
        sort = f"{field} {direction}, {sort}"
    if after is not None:
        value, domain = after
        if field == "domain":
            conditions.append(f"domain {comparison} ?")
            parameters.append(domain)
        else:
            if field in _DATE_FIELDS:
                value = _date_micros(datetime.fromisoformat(value))
            conditions.append(f"({field}, domain) {comparison} (?, ?)")
            parameters.extend((value, domain))
    database.row_factory = sqlite3.Row
    records = []
    trigram = len(query) >= 3 and database.execute("SELECT 1 FROM sqlite_master WHERE name='domain_search'").fetchone()
    if trigram:
        # A common term can match most of the catalog. Read a bounded window in
        # index order first so those searches don't enumerate every FTS match.
        base_where = "WHERE " + " AND ".join(conditions) if conditions else ""
        records = database.execute(
            f"SELECT * FROM (SELECT * FROM domains {base_where} ORDER BY {sort} LIMIT ?) WHERE instr(domain, ?) > 0 ORDER BY {sort} LIMIT ?",
            [*parameters, max(_SEARCH_PROBE_SIZE, limit), query, limit],
        ).fetchall()
    if len(records) < limit:
        if trigram:
            # MATCH treats the quoted text as a literal trigram phrase.
            conditions.append("rowid IN (SELECT rowid FROM domain_search WHERE domain_search MATCH ?)")
            parameters.append('"' + query.replace('"', '""') + '"')
        elif query:
            conditions.append("instr(domain, ?) > 0")
            parameters.append(query)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        if 0 < len(query) < 3:
            # Seek/scan only the covering sort index before loading complete
            # rows. Short, rare terms cannot use the trigram index.
            statement = f"""
                WITH chosen AS (
                    SELECT domain FROM domains {where} ORDER BY {sort} LIMIT ?
                )
                SELECT domains.* FROM chosen JOIN domains USING (domain) ORDER BY {sort}
            """
        else:
            statement = f"SELECT * FROM domains {where} ORDER BY {sort} LIMIT ?"
        records = database.execute(statement, [*parameters, limit]).fetchall()
    rows = []
    for record in records:
        row = dict(record)
        for key in _CAPTURE_IDS:
            if row[key] is not None:
                row[key] = row[key].hex()
        for key in _DATE_FIELDS:
            row[key] = _UTC_EPOCH + timedelta(microseconds=row[key])
        row["sort_value"] = row[field]
        if field in _DATE_FIELDS:
            row["sort_value"] = row[field].isoformat(timespec="microseconds")
        rows.append(row)
    return rows


def _catalog_path() -> Path:
    return CONSTANTS.CACHE_DIR / "domains-v3.sqlite3"


def _catalog_age(path: Path) -> float:
    try:
        return time() - path.stat().st_mtime
    except FileNotFoundError:
        return float("inf")


def _build(path: Path, *, force: bool, wait: bool) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use SQLite's portable process lock on a separate file. A crashed builder
    # releases the lease without touching the last published generation.
    with closing(sqlite3.connect(path.with_suffix(".lock"), timeout=60 if wait else 0)) as lease:
        try:
            lease.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as error:
            if not wait and error.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                return False
            raise
        if not force and _catalog_age(path) < _REFRESH_INTERVAL:
            return False
        building = path.with_suffix(".building")
        building.unlink(missing_ok=True)
        fd = os.open(building, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with closing(sqlite3.connect(building)) as database, database:
                # This generation is private until os.replace. Discard it on
                # failure, and keep any previous complete file readable.
                database.execute("PRAGMA journal_mode=OFF")
                _populate(database, _snapshot_batches(_snapshots()))
                _create_search_index(database)
            building.replace(path)
        finally:
            building.unlink(missing_ok=True)
    return True


def rebuild_domain_catalog() -> bool:
    """Synchronously rebuild the complete derived catalog from committed rows."""
    if connection.in_atomic_block:
        raise RuntimeError("Cannot publish a domain catalog from inside a primary database transaction")
    return _build(_catalog_path(), force=True, wait=True)


def _schedule_refresh(path: Path, *, force: bool = False) -> bool:
    global _next_refresh, _refresh_path
    if not _refresh_lock.acquire(blocking=False):
        return False
    if path == _refresh_path and monotonic() < _next_refresh:
        _refresh_lock.release()
        return False
    _refresh_path = path
    _next_refresh = monotonic() + _REFRESH_RETRY

    def refresh() -> None:
        global _next_refresh
        try:
            close_old_connections()
            _build(path, force=force, wait=False)
        except Exception:
            _next_refresh = monotonic() + _REFRESH_FAILURE_RETRY
            logger.exception("Could not build domain catalog")
        finally:
            try:
                connections.close_all()
            finally:
                _refresh_lock.release()

    try:
        Thread(target=refresh, name="domain-catalog", daemon=True).start()
    except RuntimeError:
        _next_refresh = monotonic() + _REFRESH_FAILURE_RETRY
        _refresh_lock.release()
        logger.exception("Could not schedule domain catalog build")
        return False
    return True


def domain_catalog_page(*, query="", ordering="domain", after=None, backwards=False, public=False, limit=100) -> tuple[list[dict], bool]:
    """Read a bounded domain page in cursor traversal order and report an initial build."""
    if limit <= 0 or "\x00" in query:
        return [], False
    options = dict(query=query.strip().casefold(), ordering=ordering, after=after, backwards=backwards, public=public, limit=limit)
    path = _catalog_path()
    age = _catalog_age(path)
    if age != float("inf") and not connection.in_atomic_block:
        if age >= _REFRESH_INTERVAL:
            _schedule_refresh(path)
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as database:
                return _page(database, **options), False
        except sqlite3.DatabaseError:
            if _schedule_refresh(path, force=True):
                logger.exception("Could not read domain catalog; scheduling a rebuild")
            return [], True
    initial = list(_snapshots()[: _BATCH_SIZE + 1])
    if len(initial) <= _BATCH_SIZE:
        with closing(sqlite3.connect(":memory:")) as database:
            _populate(database, [initial])
            return _page(database, **options), False
    if not connection.in_atomic_block:
        _schedule_refresh(path)
    return [], True
