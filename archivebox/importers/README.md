# Importers

Superusers connect sources at `/admin/importers/`. Plugins declare the available
providers, feeds, settings, icons, and illustrated setup steps in `config.json`.
This Django app owns configuration, scheduling, durable runs, and capture handoff.
Provider-specific browser behavior stays in plugins.

## Use

1. Install the browser extension in a dedicated Chrome profile and sign in to the
   accounts you want to archive.
2. Sync that profile to a server Persona. Select it and the expected account in
   the importer. Public feeds and CSV sources only need a URL.
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

Pause cancels pending discovery and disables the schedule. Successful batches
remain committed; starting Import all again resumes from their checkpoint. A
failed or cancelled batch never advances progress. Reset preserves captures and
run history; reset before changing an account or source with committed progress.

Discovery success and capture success are separate. Each successful nonempty
batch submits normal URL input to an ordinary Crawl using the selected Persona,
tags, and `ONLY_NEW`. Follow the capture link for actual archive results.

## Plugin contract

See the [browser importer](../../../abx-plugins/abx_plugins/plugins/importers_browser/README.md)
in the sibling repository. A plugin exposes `commands.import`, an `importers`
mapping keyed by feed ID, and JSON Schema `properties` referenced by each feed's
`config_fields`. The executable receives a versioned JSON request on stdin and
returns `ImporterItem` records followed by one `ImporterResult` on stdout.

- Source settings/checkpoints are passed through without site-specific interpretation.
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
