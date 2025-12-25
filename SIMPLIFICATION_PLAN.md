# ArchiveBox 2025 Simplification Plan

**Status:** FINAL - Ready for implementation
**Last Updated:** 2024-12-24

---

## Final Decisions Summary

| Decision | Choice |
|----------|--------|
| Task Queue | Keep `retry_at` polling pattern (no Django Tasks) |
| State Machine | Preserve current semantics; only replace mixins/statemachines if identical retry/lock guarantees are kept |
| Event Model | Remove completely |
| ABX Plugin System | Remove entirely (`archivebox/pkgs/`) |
| abx-pkg | Keep as external pip dependency (separate repo: github.com/ArchiveBox/abx-pkg) |
| Binary Providers | File-based plugins using abx-pkg internally |
| Search Backends | **Hybrid:** hooks for indexing, Python classes for querying |
| Auth Methods | Keep simple (LDAP + normal), no pluginization needed |
| ABID | Already removed (ignore old references) |
| ArchiveResult | **Keep pre-creation** with `status=queued` + `retry_at` for consistency |
| Plugin Directory | **`archivebox/plugins/*`** for built-ins, **`data/plugins/*`** for user hooks (flat `on_*__*.*` files) |
| Locking | Use `retry_at` consistently across Crawl, Snapshot, ArchiveResult |
| Worker Model | **Separate processes** per model type + per extractor, visible in htop |
| Concurrency | **Per-extractor configurable** (e.g., `ytdlp_max_parallel=5`) |
| InstalledBinary | **Keep model** + add Dependency model for audit trail |

---

## Architecture Overview

### Consistent Queue/Lock Pattern

All models (Crawl, Snapshot, ArchiveResult) use the same pattern:

```python
class StatusMixin(models.Model):
    status = models.CharField(max_length=15, db_index=True)
    retry_at = models.DateTimeField(default=timezone.now, null=True, db_index=True)

    class Meta:
        abstract = True

    def tick(self) -> bool:
        """Override in subclass. Returns True if state changed."""
        raise NotImplementedError

# Worker query (same for all models):
Model.objects.filter(
    status__in=['queued', 'started'],
    retry_at__lte=timezone.now()
).order_by('retry_at').first()

# Claim (atomic via optimistic locking):
updated = Model.objects.filter(
    id=obj.id,
    retry_at=obj.retry_at
).update(
    retry_at=timezone.now() + timedelta(seconds=60)
)
if updated == 1:  # Successfully claimed
    obj.refresh_from_db()
    obj.tick()
```

**Failure/cleanup guarantees**
- Objects stuck in `started` with a past `retry_at` must be reclaimed automatically using the existing retry/backoff rules.
- `tick()` implementations must continue to bump `retry_at` / transition to `backoff` the same way current statemachines do so that failures get retried without manual intervention.

### Process Tree (Separate Processes, Visible in htop)

```
archivebox server
├── orchestrator (pid=1000)
│   ├── crawl_worker_0 (pid=1001)
│   ├── crawl_worker_1 (pid=1002)
│   ├── snapshot_worker_0 (pid=1003)
│   ├── snapshot_worker_1 (pid=1004)
│   ├── snapshot_worker_2 (pid=1005)
│   ├── wget_worker_0 (pid=1006)
│   ├── wget_worker_1 (pid=1007)
│   ├── ytdlp_worker_0 (pid=1008)      # Limited concurrency
│   ├── ytdlp_worker_1 (pid=1009)
│   ├── screenshot_worker_0 (pid=1010)
│   ├── screenshot_worker_1 (pid=1011)
│   ├── screenshot_worker_2 (pid=1012)
│   └── ...
```

**Configurable per-extractor concurrency:**
```python
# archivebox.conf or environment
WORKER_CONCURRENCY = {
    'crawl': 2,
    'snapshot': 3,
    'wget': 2,
    'ytdlp': 2,           # Bandwidth-limited
    'screenshot': 3,
    'singlefile': 2,
    'title': 5,           # Fast, can run many
    'favicon': 5,
}
```

---

## Hook System

### Discovery (Glob at Startup)

```python
# archivebox/hooks.py
from pathlib import Path
import subprocess
import os
import json
from django.conf import settings

BUILTIN_PLUGIN_DIR = Path(__file__).parent.parent / 'plugins'
USER_PLUGIN_DIR = settings.DATA_DIR / 'plugins'

def discover_hooks(event_name: str) -> list[Path]:
    """Find all scripts matching on_{EventName}__*.{sh,py,js} under archivebox/plugins/* and data/plugins/*"""
    hooks = []
    for base in (BUILTIN_PLUGIN_DIR, USER_PLUGIN_DIR):
        if not base.exists():
            continue
        for ext in ('sh', 'py', 'js'):
            hooks.extend(base.glob(f'*/on_{event_name}__*.{ext}'))
    return sorted(hooks)

def run_hook(script: Path, output_dir: Path, **kwargs) -> dict:
    """Execute hook with --key=value args, cwd=output_dir."""
    args = [str(script)]
    for key, value in kwargs.items():
        args.append(f'--{key.replace("_", "-")}={json.dumps(value, default=str)}')

    env = os.environ.copy()
    env['ARCHIVEBOX_DATA_DIR'] = str(settings.DATA_DIR)

    result = subprocess.run(
        args,
        cwd=output_dir,
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )
    return {
        'returncode': result.returncode,
        'stdout': result.stdout,
        'stderr': result.stderr,
    }
```

### Hook Interface

- **Input:** CLI args `--url=... --snapshot-id=...`
- **Location:** Built-in hooks in `archivebox/plugins/<plugin>/on_*__*.*`, user hooks in `data/plugins/<plugin>/on_*__*.*`
- **Internal API:** Should treat ArchiveBox as an external CLI—call `archivebox config --get ...`, `archivebox find ...`, import `abx-pkg` only when running in their own venvs.
- **Output:** Files written to `$PWD` (the output_dir), can call `archivebox create ...`
- **Logging:** stdout/stderr captured to ArchiveResult
- **Exit code:** 0 = success, non-zero = failure

---

## Unified Config Access

- Implement `archivebox.config.get_config(scope='global'|'crawl'|'snapshot'|...)` that merges defaults, config files, environment variables, DB overrides, and per-object config (seed/crawl/snapshot).
- Provide helpers (`get_config()`, `get_flat_config()`) for Python callers so `abx.pm.hook.get_CONFIG*` can be removed.
- Ensure the CLI command `archivebox config --get KEY` (and a machine-readable `--format=json`) uses the same API so hook scripts can query config via subprocess calls.
- Document that plugin hooks should prefer the CLI to fetch config rather than importing Django internals, guaranteeing they work from shell/bash/js without ArchiveBox’s runtime.

---

### Example Extractor Hooks

**Bash:**
```bash
#!/usr/bin/env bash
# plugins/on_Snapshot__wget.sh
set -e

# Parse args
for arg in "$@"; do
    case $arg in
        --url=*) URL="${arg#*=}" ;;
        --snapshot-id=*) SNAPSHOT_ID="${arg#*=}" ;;
    esac
done

# Find wget binary
WGET=$(archivebox find InstalledBinary --name=wget --format=abspath)
[ -z "$WGET" ] && echo "wget not found" >&2 && exit 1

# Run extraction (writes to $PWD)
$WGET --mirror --page-requisites --adjust-extension "$URL" 2>&1

echo "Completed wget mirror of $URL"
```

**Python:**
```python
#!/usr/bin/env python3
# plugins/on_Snapshot__singlefile.py
import argparse
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--snapshot-id', required=True)
    args = parser.parse_args()

    # Find binary via CLI
    result = subprocess.run(
        ['archivebox', 'find', 'InstalledBinary', '--name=single-file', '--format=abspath'],
        capture_output=True, text=True
    )
    bin_path = result.stdout.strip()
    if not bin_path:
        print("single-file not installed", file=sys.stderr)
        sys.exit(1)

    # Run extraction (writes to $PWD)
    subprocess.run([bin_path, args.url, '--output', 'singlefile.html'], check=True)
    print(f"Saved {args.url} to singlefile.html")

if __name__ == '__main__':
    main()
```

---

## Binary Providers & Dependencies

- Move dependency tracking into a dedicated `dependencies` module (or extend `archivebox/machine/`) with two Django models:

```yaml
Dependency:
    id: uuidv7
    bin_name: extractor binary executable name (ytdlp|wget|screenshot|...)
    bin_provider: apt | brew | pip | npm | gem | nix | '*' for any
    custom_cmds: JSON of provider->install command overrides (optional)
    config: JSON of env vars/settings to apply during install
    created_at: utc datetime

InstalledBinary:
    id: uuidv7
    dependency: FK to Dependency
    bin_name: executable name again
    bin_abspath: filesystem path
    bin_version: semver string
    bin_hash: sha256 of the binary
    bin_provider: apt | brew | pip | npm | gem | nix | custom | ...
    created_at: utc datetime (last seen/installed)
    is_valid: property returning True when both abspath+version are set
```

- Provide CLI commands for hook scripts: `archivebox find InstalledBinary --name=wget --format=abspath`, `archivebox dependency create ...`, etc.
- Hooks remain language agnostic and should not import ArchiveBox Django modules; they rely on CLI commands plus their own runtime (python/bash/js).

### Provider Hooks

- Built-in provider plugins live under `archivebox/plugins/<provider>/on_Dependency__*.py` (e.g., apt, brew, pip, custom).
- Each provider hook:
    1. Checks if the Dependency allows that provider via `bin_provider` or wildcard `'*'`.
    2. Builds the install command (`custom_cmds[provider]` override or sane default like `apt install -y <bin_name>`).
    3. Executes the command (bash/python) and, on success, records/updates an `InstalledBinary`.

Example outline (bash or python, but still interacting via CLI):

```bash
# archivebox/plugins/apt/on_Dependency__install_using_apt_provider.sh
set -euo pipefail

DEP_JSON=$(archivebox dependency show --id="$DEPENDENCY_ID" --format=json)
BIN_NAME=$(echo "$DEP_JSON" | jq -r '.bin_name')
PROVIDER_ALLOWED=$(echo "$DEP_JSON" | jq -r '.bin_provider')

if [[ "$PROVIDER_ALLOWED" == "*" || "$PROVIDER_ALLOWED" == *"apt"* ]]; then
    INSTALL_CMD=$(echo "$DEP_JSON" | jq -r '.custom_cmds.apt // empty')
    INSTALL_CMD=${INSTALL_CMD:-"apt install -y --no-install-recommends $BIN_NAME"}
    bash -lc "$INSTALL_CMD"

    archivebox dependency register-installed \
        --dependency-id="$DEPENDENCY_ID" \
        --bin-provider=apt \
        --bin-abspath="$(command -v "$BIN_NAME")" \
        --bin-version="$("$(command -v "$BIN_NAME")" --version | head -n1)" \
        --bin-hash="$(sha256sum "$(command -v "$BIN_NAME")" | cut -d' ' -f1)"
fi
```

- Extractor-level hooks (e.g., `archivebox/plugins/wget/on_Crawl__install_wget_extractor_if_needed.*`) ensure dependencies exist before starting work by creating/updating `Dependency` records (via CLI) and then invoking provider hooks.
- Remove all reliance on `abx.pm.hook.binary_load` / ABX plugin packages; `abx-pkg` can remain as a normal pip dependency that hooks import if useful.

---

## Search Backends (Hybrid)

### Indexing: Hook Scripts

Triggered when ArchiveResult completes successfully (from the Django side we simply fire the event; indexing logic lives in standalone hook scripts):

```python
#!/usr/bin/env python3
# plugins/on_ArchiveResult__index_sqlitefts.py
import argparse
import sqlite3
import os
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot-id', required=True)
    parser.add_argument('--extractor', required=True)
    args = parser.parse_args()

    # Read text content from output files
    content = ""
    for f in Path.cwd().rglob('*.txt'):
        content += f.read_text(errors='ignore') + "\n"
    for f in Path.cwd().rglob('*.html'):
        content += strip_html(f.read_text(errors='ignore')) + "\n"

    if not content.strip():
        return

    # Add to FTS index
    db = sqlite3.connect(os.environ['ARCHIVEBOX_DATA_DIR'] + '/search.sqlite3')
    db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(snapshot_id, content)')
    db.execute('INSERT OR REPLACE INTO fts VALUES (?, ?)', (args.snapshot_id, content))
    db.commit()

if __name__ == '__main__':
    main()
```

### Querying: CLI-backed Python Classes

```python
# archivebox/search/backends/sqlitefts.py
import subprocess
import json

class SQLiteFTSBackend:
    name = 'sqlitefts'

    def search(self, query: str, limit: int = 50) -> list[str]:
        """Call plugins/on_Search__query_sqlitefts.* and parse stdout."""
        result = subprocess.run(
            ['archivebox', 'search-backend', '--backend', self.name, '--query', query, '--limit', str(limit)],
            capture_output=True,
            check=True,
            text=True,
        )
        return json.loads(result.stdout or '[]')


# archivebox/search/__init__.py
from django.conf import settings

def get_backend():
    name = getattr(settings, 'SEARCH_BACKEND', 'sqlitefts')
    if name == 'sqlitefts':
        from .backends.sqlitefts import SQLiteFTSBackend
        return SQLiteFTSBackend()
    elif name == 'sonic':
        from .backends.sonic import SonicBackend
        return SonicBackend()
    raise ValueError(f'Unknown search backend: {name}')

def search(query: str) -> list[str]:
    return get_backend().search(query)
```

- Each backend script lives under `archivebox/plugins/search/on_Search__query_<backend>.py` (with user overrides in `data/plugins/...`) and outputs JSON list of snapshot IDs. Python wrappers simply invoke the CLI to keep Django isolated from backend implementations.

---

## Simplified Models

> Goal: reduce line count without sacrificing the correctness guarantees we currently get from `ModelWithStateMachine` + python-statemachine. We keep the mixins/statemachines unless we can prove a smaller implementation enforces the same transitions/retry locking.

### Snapshot

```python
class Snapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    url = models.URLField(unique=True, db_index=True)
    timestamp = models.CharField(max_length=32, unique=True, db_index=True)
    title = models.CharField(max_length=512, null=True, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    modified_at = models.DateTimeField(auto_now=True)

    crawl = models.ForeignKey('crawls.Crawl', on_delete=models.CASCADE, null=True)
    tags = models.ManyToManyField('Tag', through='SnapshotTag')

    # Status (consistent with Crawl, ArchiveResult)
    status = models.CharField(max_length=15, default='queued', db_index=True)
    retry_at = models.DateTimeField(default=timezone.now, null=True, db_index=True)

    # Inline fields (no mixins)
    config = models.JSONField(default=dict)
    notes = models.TextField(blank=True, default='')

    FINAL_STATES = ['sealed']

    @property
    def output_dir(self) -> Path:
        return settings.ARCHIVE_DIR / self.timestamp

    def tick(self) -> bool:
        if self.status == 'queued' and self.can_start():
            self.start()
            return True
        elif self.status == 'started' and self.is_finished():
            self.seal()
            return True
        return False

    def can_start(self) -> bool:
        return bool(self.url)

    def is_finished(self) -> bool:
        results = self.archiveresult_set.all()
        if not results.exists():
            return False
        return not results.filter(status__in=['queued', 'started', 'backoff']).exists()

    def start(self):
        self.status = 'started'
        self.retry_at = timezone.now() + timedelta(seconds=10)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.save()
        self.create_pending_archiveresults()

    def seal(self):
        self.status = 'sealed'
        self.retry_at = None
        self.save()

    def create_pending_archiveresults(self):
        for extractor in get_config(defaults=settings, crawl=self.crawl, snapshot=self).ENABLED_EXTRACTORS:
            ArchiveResult.objects.get_or_create(
                snapshot=self,
                extractor=extractor,
                defaults={
                    'status': 'queued',
                    'retry_at': timezone.now(),
                    'created_by': self.created_by,
                }
            )
```

### ArchiveResult

```python
class ArchiveResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7)
    snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)
    extractor = models.CharField(max_length=32, db_index=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)
    modified_at = models.DateTimeField(auto_now=True)

    # Status
    status = models.CharField(max_length=15, default='queued', db_index=True)
    retry_at = models.DateTimeField(default=timezone.now, null=True, db_index=True)

    # Execution
    start_ts = models.DateTimeField(null=True)
    end_ts = models.DateTimeField(null=True)
    output = models.CharField(max_length=1024, null=True)
    cmd = models.JSONField(null=True)
    pwd = models.CharField(max_length=256, null=True)

    # Audit trail
    machine = models.ForeignKey('machine.Machine', on_delete=models.SET_NULL, null=True)
    iface = models.ForeignKey('machine.NetworkInterface', on_delete=models.SET_NULL, null=True)
    installed_binary = models.ForeignKey('machine.InstalledBinary', on_delete=models.SET_NULL, null=True)

    FINAL_STATES = ['succeeded', 'failed']

    class Meta:
        unique_together = ('snapshot', 'extractor')

    @property
    def output_dir(self) -> Path:
        return self.snapshot.output_dir / self.extractor

    def tick(self) -> bool:
        if self.status == 'queued' and self.can_start():
            self.start()
            return True
        elif self.status == 'backoff' and self.can_retry():
            self.status = 'queued'
            self.retry_at = timezone.now()
            self.save()
            return True
        return False

    def can_start(self) -> bool:
        return bool(self.snapshot.url)

    def can_retry(self) -> bool:
        return self.retry_at and self.retry_at <= timezone.now()

    def start(self):
        self.status = 'started'
        self.start_ts = timezone.now()
        self.retry_at = timezone.now() + timedelta(seconds=120)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.save()

        # Run hook and complete
        self.run_extractor_hook()

    def run_extractor_hook(self):
        from archivebox.hooks import discover_hooks, run_hook

        hooks = discover_hooks(f'Snapshot__{self.extractor}')
        if not hooks:
            self.status = 'failed'
            self.output = f'No hook for: {self.extractor}'
            self.end_ts = timezone.now()
            self.retry_at = None
            self.save()
            return

        result = run_hook(
            hooks[0],
            output_dir=self.output_dir,
            url=self.snapshot.url,
            snapshot_id=str(self.snapshot.id),
        )

        self.status = 'succeeded' if result['returncode'] == 0 else 'failed'
        self.output = result['stdout'][:1024] or result['stderr'][:1024]
        self.end_ts = timezone.now()
        self.retry_at = None
        self.save()

        # Trigger search indexing if succeeded
        if self.status == 'succeeded':
            self.trigger_search_indexing()

    def trigger_search_indexing(self):
        from archivebox.hooks import discover_hooks, run_hook
        for hook in discover_hooks('ArchiveResult__index'):
            run_hook(hook, output_dir=self.output_dir,
                     snapshot_id=str(self.snapshot.id),
                     extractor=self.extractor)
```

- `ArchiveResult` must continue storing execution metadata (`cmd`, `pwd`, `machine`, `iface`, `installed_binary`, timestamps) exactly as before, even though the extractor now runs via hook scripts. `run_extractor_hook()` is responsible for capturing those values (e.g., wrapping subprocess calls).
- Any refactor of `Snapshot`, `ArchiveResult`, or `Crawl` has to keep the same `FINAL_STATES`, `retry_at` semantics, and tag/output directory handling that `ModelWithStateMachine` currently provides.

---

## Simplified Worker System

```python
# archivebox/workers/orchestrator.py
import os
import time
import multiprocessing
from datetime import timedelta
from django.utils import timezone
from django.conf import settings


class Worker:
    """Base worker for processing queued objects."""
    Model = None
    name = 'worker'

    def get_queue(self):
        return self.Model.objects.filter(
            retry_at__lte=timezone.now()
        ).exclude(
            status__in=self.Model.FINAL_STATES
        ).order_by('retry_at')

    def claim(self, obj) -> bool:
        """Atomic claim via optimistic lock."""
        updated = self.Model.objects.filter(
            id=obj.id,
            retry_at=obj.retry_at
        ).update(retry_at=timezone.now() + timedelta(seconds=60))
        return updated == 1

    def run(self):
        print(f'[{self.name}] Started pid={os.getpid()}')
        while True:
            obj = self.get_queue().first()
            if obj and self.claim(obj):
                try:
                    obj.refresh_from_db()
                    obj.tick()
                except Exception as e:
                    print(f'[{self.name}] Error: {e}')
                    obj.retry_at = timezone.now() + timedelta(seconds=60)
                    obj.save(update_fields=['retry_at'])
            else:
                time.sleep(0.5)


class CrawlWorker(Worker):
    from crawls.models import Crawl
    Model = Crawl
    name = 'crawl'


class SnapshotWorker(Worker):
    from core.models import Snapshot
    Model = Snapshot
    name = 'snapshot'


class ExtractorWorker(Worker):
    """Worker for a specific extractor."""
    from core.models import ArchiveResult
    Model = ArchiveResult

    def __init__(self, extractor: str):
        self.extractor = extractor
        self.name = extractor

    def get_queue(self):
        return super().get_queue().filter(extractor=self.extractor)


class Orchestrator:
    def __init__(self):
        self.processes = []

    def spawn(self):
        config = settings.WORKER_CONCURRENCY

        for i in range(config.get('crawl', 2)):
            self._spawn(CrawlWorker, f'crawl_{i}')

        for i in range(config.get('snapshot', 3)):
            self._spawn(SnapshotWorker, f'snapshot_{i}')

        for extractor, count in config.items():
            if extractor in ('crawl', 'snapshot'):
                continue
            for i in range(count):
                self._spawn(ExtractorWorker, f'{extractor}_{i}', extractor)

    def _spawn(self, cls, name, *args):
        worker = cls(*args) if args else cls()
        worker.name = name
        p = multiprocessing.Process(target=worker.run, name=name)
        p.start()
        self.processes.append(p)

    def run(self):
        print(f'Orchestrator pid={os.getpid()}')
        self.spawn()
        try:
            while True:
                for p in self.processes:
                    if not p.is_alive():
                        print(f'{p.name} died, restarting...')
                        # Respawn logic
                time.sleep(5)
        except KeyboardInterrupt:
            for p in self.processes:
                p.terminate()
```

---

## Directory Structure

```
archivebox-nue/
├── archivebox/
│   ├── __init__.py
│   ├── config.py                    # Simple env-based config
│   ├── hooks.py                     # Hook discovery + execution
│   │
│   ├── core/
│   │   ├── models.py                # Snapshot, ArchiveResult, Tag
│   │   ├── admin.py
│   │   └── views.py
│   │
│   ├── crawls/
│   │   ├── models.py                # Crawl, Seed, CrawlSchedule, Outlink
│   │   └── admin.py
│   │
│   ├── machine/
│   │   ├── models.py                # Machine, NetworkInterface, Dependency, InstalledBinary
│   │   └── admin.py
│   │
│   ├── workers/
│   │   └── orchestrator.py          # ~150 lines
│   │
│   ├── api/
│   │   └── ...
│   │
│   ├── cli/
│   │   └── ...
│   │
│   ├── search/
│   │   ├── __init__.py
│   │   └── backends/
│   │       ├── sqlitefts.py
│   │       └── sonic.py
│   │
│   ├── index/
│   ├── parsers/
│   ├── misc/
│   └── templates/
│
-├── plugins/                         # Built-in hooks (ArchiveBox never imports these directly)
│   ├── wget/
│   │   └── on_Snapshot__wget.sh
│   ├── dependencies/
│   │   ├── on_Dependency__install_using_apt_provider.sh
│   │   └── on_Dependency__install_using_custom_bash.py
│   ├── search/
│   │   ├── on_ArchiveResult__index_sqlitefts.py
│   │   └── on_Search__query_sqlitefts.py
│   └── ...
├── data/
│   └── plugins/                     # User-provided hooks mirror builtin layout
└── pyproject.toml
```

---

## Implementation Phases

### Phase 1: Build Unified Config + Hook Scaffold

1. Implement `archivebox.config.get_config()` + CLI plumbing (`archivebox config --get ... --format=json`) without touching abx yet.
2. Add `archivebox/hooks.py` with dual plugin directories (`archivebox/plugins`, `data/plugins`), discovery, and execution helpers.
3. Keep the existing ABX/worker system running while new APIs land; surface warnings where `abx.pm.*` is still in use.

### Phase 2: Gradual ABX Removal

1. Rename `archivebox/pkgs/` to `archivebox/pkgs.unused/` and start deleting packages once equivalent hook scripts exist.
2. Remove `pluggy`, `python-statemachine`, and all `abx-*` dependencies/workspace entries from `pyproject.toml` only after consumers are migrated.
3. Replace every `abx.pm.hook.get_*` usage in CLI/config/search/extractors with the new config + hook APIs.

### Phase 3: Worker + State Machine Simplification

1. Introduce the process-per-model orchestrator while preserving `ModelWithStateMachine` semantics (Snapshot/Crawl/ArchiveResult).
2. Only drop mixins/statemachine dependency after verifying the new `tick()` implementations keep retries/backoff/final states identical.
3. Ensure Huey/task entry points either delegate to the new orchestrator or are retired cleanly so background work isn’t double-run.

### Phase 4: Hook-Based Extractors & Dependencies

1. Create builtin extractor hooks in `archivebox/plugins/*/on_Snapshot__*.{sh,py,js}`; have `ArchiveResult.run_extractor_hook()` capture cmd/pwd/machine/install metadata.
2. Implement the new `Dependency`/`InstalledBinary` models + CLI commands, and port provider/install logic into hook scripts that only talk via CLI.
3. Add CLI helpers `archivebox find InstalledBinary`, `archivebox dependency ...` used by all hooks and document how user plugins extend them.

### Phase 5: Search Backends & Indexing Hooks

1. Migrate indexing triggers to hook scripts (`on_ArchiveResult__index_*`) that run standalone and write into `$ARCHIVEBOX_DATA_DIR/search.*`.
2. Implement CLI-driven query hooks (`on_Search__query_*`) plus lightweight Python wrappers in `archivebox/search/backends/`.
3. Remove any remaining ABX search integration.


---

## What Gets Deleted

```
archivebox/pkgs/                 # ~5,000 lines
archivebox/workers/actor.py      # If exists
```

## Dependencies Removed

```toml
"pluggy>=1.5.0"
"python-statemachine>=2.3.6"
# + all 30 abx-* packages
```

## Dependencies Kept

```toml
"django>=6.0"
"django-ninja>=1.3.0"
"abx-pkg>=0.6.0"         # External, for binary management
"click>=8.1.7"
"rich>=13.8.0"
```

---

## Estimated Savings

| Component | Lines Removed |
|-----------|---------------|
| pkgs/ (ABX) | ~5,000 |
| statemachines | ~300 |
| workers/ | ~500 |
| base_models mixins | ~100 |
| **Total** | **~6,000 lines** |

Plus 30+ dependencies removed, massive reduction in conceptual complexity.

---

**Status: READY FOR IMPLEMENTATION**

Begin with Phase 1: Rename `archivebox/pkgs/` to add `.unused` suffix (delete after porting) and fix imports.
