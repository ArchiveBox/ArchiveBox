# ArchiveBox Architecture Diagrams

This page is a map of the current execution and persistence paths. The implementation lives primarily in:

- `archivebox/cli/` for CLI entry points
- `archivebox/services/runner.py` for crawl and snapshot execution
- `archivebox/crawls/models.py` for the `Crawl` model and its atomic queue transitions
- `archivebox/core/models.py` for `Snapshot`, `ArchiveResult`, and Snapshot queue transitions
- `archivebox/services/` for bus event projectors
- `abxpkg` and `abx-plugins` for binary resolution and plugin hooks

## High-Level Execution Flow

```mermaid
flowchart TD
    ENTRY["CLI, Web UI, REST API, or scheduler"] --> CRAWL["Create or resume a Crawl row"]
    CRAWL --> RUNNER["run_crawl() / CrawlRunner"]
    RUNNER --> DISCOVER["Create or select Snapshot rows"]
    DISCOVER --> EVENTS["Emit crawl and snapshot lifecycle events"]
    EVENTS --> PLUGINS["Run selected abx-plugin hooks"]
    PLUGINS --> PROCESSES["Persist Process rows and hook output"]
    PROCESSES --> RESULTS["Project ArchiveResult rows"]
    RESULTS --> FILES["Write snapshot output files"]
    RESULTS --> SNAPSTATE["Seal or requeue Snapshot"]
    SNAPSTATE --> CRAWLSTATE["Seal, pause, or continue Crawl"]

    EVENTS --> BINREQ["BinaryRequestEvent"]
    BINREQ --> ABXPKG["abxpkg resolution"]
    ABXPKG --> HOST["Compatible host binary"]
    ABXPKG --> MANAGED["Managed install fallback"]
    HOST --> ENV["Project resolved binary into LIB_DIR/env/bin"]
    MANAGED --> ENV

    CRAWL -.-> DB["SQLite database"]
    PROCESSES -.-> DB
    RESULTS -.-> DB
    FILES -.-> STORAGE["archive/users/... snapshot storage"]
```

ArchiveBox has one normal crawl execution path. CLI commands and web/API actions create or select database rows, then call the same runner. The runner emits lifecycle events, abx-plugin hooks do the extraction work, and service projectors persist processes and results.

Binary discovery and installation always goes through abxpkg. Compatible host binaries are preferred; managed providers are the fallback. Resolved binaries are projected into `LIB_DIR/env/bin` before programmatic use. `LIB_DIR/bin` is only a convenience directory for humans.

## Persistent Data

```mermaid
flowchart LR
    DATA["ArchiveBox data directory"] --> DB["index.sqlite3"]
    DATA --> ARCHIVE["archive/users/&lt;user&gt;/snapshots/&lt;date&gt;/&lt;domain&gt;/&lt;uuid&gt;/"]
    DATA --> SOURCES["sources/"]
    DATA --> LOGS["logs/"]
    DATA --> LIB["lib/env/bin/ resolved binaries"]

    ARCHIVE --> PLUGINOUT["Plugin-namespaced outputs"]
    ARCHIVE --> META["Snapshot metadata and indexes"]
```

The database is the source of truth for model state. Snapshot directories contain captured artifacts and rendered metadata. Older collections may also contain legacy timestamp-named snapshot directories.

## `Crawl` Queue Lifecycle

Implemented directly by `Crawl` in `archivebox/crawls/models.py`. The database
row is the durable state; the runner claims `retry_at` with a conditional update
before it performs side effects, then calls the model's explicit lifecycle
methods. There is deliberately no second in-memory state machine that can drift
from the row owned by another process.

```mermaid
stateDiagram-v2
    [*] --> QUEUED
    QUEUED --> STARTED: runner claim and valid URLs
    QUEUED --> QUEUED: claimed but not ready
    QUEUED --> SEALED: all existing snapshots finished
    STARTED --> SEALED: all snapshots finished
    QUEUED --> PAUSED: pause requested
    STARTED --> PAUSED: pause requested
    PAUSED --> QUEUED: resume requested
    PAUSED --> PAUSED: not runnable
    QUEUED --> SEALED: explicit seal
    STARTED --> SEALED: explicit seal
    PAUSED --> SEALED: explicit seal
    SEALED --> [*]
```

A crawl owns a set of snapshots. The runner creates or discovers those snapshots and projects crawl events while the row is `STARTED`; sealing waits for their normal lifecycle to finish. Pausing also schedules child snapshots to pause, and resuming returns the crawl to the runnable queue. Scheduled maintenance is dispatched directly by `CrawlSchedule`; it does not create a synthetic crawl or snapshot.

## `Snapshot` Queue Lifecycle

Implemented directly by `Snapshot` in `archivebox/core/models.py`, using the
same conditional `retry_at` claim protocol as `Crawl`.

```mermaid
stateDiagram-v2
    [*] --> QUEUED
    QUEUED --> STARTED: runner claim and URL is ready
    QUEUED --> QUEUED: claimed but not ready
    QUEUED --> SEALED: all existing results finished
    STARTED --> SEALED: all hook results finished
    QUEUED --> PAUSED: pause requested
    STARTED --> PAUSED: pause requested
    PAUSED --> QUEUED: resume requested
    PAUSED --> PAUSED: not runnable
    QUEUED --> SEALED: explicit seal
    STARTED --> SEALED: explicit seal
    PAUSED --> SEALED: explicit seal
    SEALED --> [*]
```

The runner creates one queued `ArchiveResult` per selected hook, executes those hooks through the shared event bus, and seals the snapshot after every result reaches a final status. The narrow search-index maintenance operation on an already sealed snapshot is the intentional exception; it does not reopen or invent a second general lifecycle path.

## `ArchiveResult` Projection

`ArchiveResult` is not driven by a separate in-memory state machine. The runner creates queued rows, and `ArchiveResultService` projects `ArchiveResultEvent` and `ProcessCompletedEvent` data into them.

```mermaid
flowchart LR
    QUEUED["queued"] --> STARTED["started"]
    STARTED --> SUCCEEDED["succeeded"]
    STARTED --> FAILED["failed"]
    STARTED --> SKIPPED["skipped"]
    STARTED --> NORESULTS["noresults"]
    STARTED -. recoverable wait .-> BACKOFF["backoff"]
    BACKOFF -. resumed work .-> STARTED
```

`succeeded`, `failed`, `skipped`, and `noresults` are final result statuses. Each row identifies the plugin and hook that produced it and stores structured output, file metadata, timing, and error details.
