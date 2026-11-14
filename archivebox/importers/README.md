# Importers

Superusers connect sources at `/admin/importers/`. Plugins declare the available
providers, feeds, settings, icons, and illustrated setup steps in `config.json`.
This Django app owns configuration, scheduling, durable runs, and capture handoff.
Provider-specific browser behavior stays in plugins.

## Use

1. Install the browser extension in a dedicated Chrome profile and sign in to the
   accounts you want to archive.
2. Sync that profile to a server Persona and select it in the importer. The
   signed-in account is detected automatically and remembered after verification.
   Public feeds and CSV sources only need a URL.
3. **Check access**, then **Preview**. Neither advances progress or creates captures.
4. **Import all** continues through every batch until the plugin reports the end
   of the available history. Advanced options contain batch size, tags, schedule,
   optional source overrides, and a display name. Batch size is never a total cap.

The ordinary server worker processes imports. CLI equivalents:

```sh
archivebox manage importers --source SOURCE_UUID --action preview
archivebox manage importers --source SOURCE_UUID --action import
archivebox manage importers --due
```

Native commands expose source configuration and run history:

```sh
archivebox importer catalog
archivebox importer create --plugin importer_rss --feed feed --settings '{"IMPORTER_RSS_URL":"https://example.com/feed.xml"}'
archivebox importer list --format csv
archivebox importer update SOURCE_UUID --data '{"folder_id":"FOLDER_UUID","schedule":"daily"}'
archivebox importer action SOURCE_UUID preview
archivebox importer action SOURCE_UUID import
archivebox importer runs --source-id SOURCE_UUID --format jsonl
archivebox importer action SOURCE_UUID pause
archivebox importer delete SOURCE_UUID --yes
```

The optional folder destination applies to newly discovered captures through their
native Crawl. Parent folders use their Items destination; ordinary smart folders
cannot receive captures. Sources and run history export CSV, TSV, JSON, and JSONL
with separate foreign-key IDs and names. The UI includes CSV/JSONL download links.

Authenticated REST endpoints under `/api/v1/importers/` expose `catalog`,
`sources` (GET/POST), `source/{id}` (GET/PATCH/DELETE),
`source/{id}/{action}` (POST), `runs` (GET, with `source_id`, `limit`, `offset`),
and `run/{id}` (GET). Source and run lists accept `format=csv|tsv|jsonl|json`.
Run status is owned by the worker; use source actions to queue or cancel work.
Active sources cannot be edited or deleted. Settings/checkpoints remain private.

ImporterSource and ImporterRun emit CREATE/UPDATE/DELETE webhooks; ImporterRun
also emits STARTED and COMPLETED on status transitions, including conditional
worker writes and cancellation. Completion payloads include the committed crawl
relationship. Export jobs use Process STARTED/EXITED events (`worker_type=site-export`).

Pause cancels pending discovery and disables the schedule. Successful batches
remain committed; starting Import all again resumes from their checkpoint. A
failed or cancelled batch never advances progress. Reset preserves captures and
run history; reset before changing an account or source with committed progress.

Discovery success and capture success are separate. Each successful nonempty
batch submits normal URL input to an ordinary Crawl using the selected Persona,
tags, and `ONLY_NEW`. Each run links to its Crawl and filtered snapshot list;
linked captures may still be queued after discovery finishes. Source and run pages
link to their Persona and all recorded AI sessions. Run details include timestamps,
latest recorded agent activity, failures, and authenticated private logs. History
is paginated; bounded log reads are loaded separately from the initial HTML.

**Learned code** shows the absolute server directory containing the adapter and
Browser Harness / Stagehand workspace. You can optionally manage it with your own
version control. **Reset learned code** uses the existing worker and excludes
concurrent discovery; it removes generated state while preserving a root `.git`,
progress, captures, Persona cookies, and run history. The next browser run learns
again. **Reset progress** is a separate action.

## Plugin contract

See the [browser importer](https://github.com/ArchiveBox/abx-plugins/blob/main/abx_plugins/plugins/importers_browser/README.md)
in the sibling repository. A plugin exposes `commands.import`, an `importers`
mapping keyed by feed ID, and JSON Schema `properties` referenced by each feed's
`config_fields`. The executable receives a versioned JSON request on stdin and
returns `ImporterItem` records followed by one `ImporterResult` on stdout.

- Source settings/checkpoints are passed through without site-specific interpretation.
- Optional `ImporterItem.metadata.tags` is a list of tag names applied to that item’s capture.
- Account identity must stay stable. Login problems stop scheduling.
- `has_more=true` must advance the checkpoint; continuation is committed with the
  previous batch. `has_more=false` must mean the actual source is exhausted.
- A rate limit, site cap, loading failure, or truncated response is not completion.
- Plugin output, account names, titles, and setup text are escaped in the UI.
- Run JSON downloads exclude settings and checkpoints. Private run logs and learned
  scripts live under `DATA_DIR/importers/SOURCE_UUID/`; they are not public assets.
- DB transactions contain only short DB work, never browser/network/filesystem work.

Setup images are plugin-owned files, served through authenticated importer routes.
Use clean demonstration collections/accounts for shipped images; never include
real personal account details or credentials.

## Verification

```sh
uv run pytest archivebox/tests/test_importers.py -q
```

The tests use real HTTP feeds/CSV files, executable plugin commands, database rows,
and ordinary title/wget captures. Live social-site validation is additionally
required: successful preview alone does not establish full-history completeness.
