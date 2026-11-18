---
name: archivebox
description: Use this when working on the ArchiveBox app, CLI, server, Docker image, Admin UI, REST API, data dirs, crawls, snapshots, and release/deploy scripts.
---

# ArchiveBox

## Purpose

ArchiveBox is the full self-hosted web archiving app. Use this skill for collection operations, app code, Docker, Admin UI, API, and release work.

## Shared Rules

- Keep this repo on branch `dev`.
- Use `uv` and `uv run` for Python commands.
- Do not use system `python`, direct `.venv/bin/python`, or `pip` commands.
- Use existing ArchiveBox CLI/API/UI/runner paths for setup and side effects.
- Do not mock, monkeypatch, fake, simulate, skip, xfail, or weaken tests.
- Verify behavior with real commands, real data dirs, real DB rows, real hooks, real browsers, and real filesystem outputs.
- Read `README.md` for the full setup, CLI, Docker, API, and release surface.

## Development Setup

```bash
uv sync --dev --all-extras
mkdir -p data
cd data
uv run --project .. archivebox init
uv run --project .. archivebox install
```

## User-Facing Setup

Recommended CLI install:

```bash
uv tool install --python 3.13 --prerelease explicit --upgrade 'git+https://github.com/ArchiveBox/ArchiveBox.git@dev'
mkdir -p ~/archivebox/data
cd ~/archivebox/data
archivebox init
archivebox install
archivebox add --plugins=parse_txt_urls 'https://example.com/'
```

Alternative install methods:

- Docker Compose / Docker
- Homebrew
- Debian package
- pip

## Basic Usage

Run from inside an initialized data dir:

```bash
cd ~/archivebox/data
archivebox version
archivebox status
archivebox install
archivebox add --plugins=parse_txt_urls 'https://example.com/docs-basic-usage'
archivebox list --json --with-headers
archivebox search 'example'
archivebox update --filter-type=domain example.com
archivebox remove --yes --delete --filter-type=exact 'https://example.com/docs-basic-usage'
archivebox run
```

## Importers, Domains, and Rules Engine

- **Importers**, `/admin/importers/`: choose a provider, persona, folder/tags and schedule. Inspect `archivebox importer catalog`, then create a source:
  ```sh
  archivebox importer create --plugin importer_rss --feed feed --name Docs --settings '{"IMPORTER_RSS_URL":"https://example.org/feed.xml"}' --tags docs
  archivebox importer action UUID preview
  archivebox importer runs --source-id UUID --limit 5
  ```
  Replace UUID with the returned ID. Review the queued preview before `archivebox importer action UUID import`; queued is not completed. REST: `/api/v1/importers/`.
- **Domains**, `/admin/domains/`: browse/replay/export a host or request a bounded crawl, e.g. `https://example.org/docs/`, depth 1, max 20 pages, subpaths only.
- **Rules Engine/Webhooks**, `/admin/webhooks/`: e.g. Snapshot → Before capture → selected folder → Add tags `review`. Preview matches without executing actions. HTTP(S), native Python and shell actions support arbitrarily complex triggers/automations: custom crawler discovers URLs → `archivebox add URL` → Snapshot Capture completed → callback to a trusted handler that postprocesses downloads. Continue through the Python API, CLI or REST API; HTTP receivers run their own commands.
  Authorize code, data and recipients; deduplicate event/object IDs and bound callback loops.
  Keep scripts in the webhook's Python/shell action field when practical so admins can edit them in the UI; avoid ad-hoc script files.
- **Organization/settings**: `archivebox folder list`, `archivebox persona --help`, `archivebox config --get KEY` / `--set KEY=VALUE`.

### Before extending ArchiveBox

1. Inspect config, the plugin catalog and UI/API for existing or near matches: OCR, media/subtitles/transcripts, 3D/CAD, PDFs/papers, Git/forums. Prefer an existing extension, library or CLI over custom internals.
2. Compose native features or Rules Engine webhooks/hooks/Python/shell before writing custom code; stay within authorized scope.
3. Write custom code last, or when directly requested: copy a comparable built-in into `custom_plugins/<name>/`, use existing discovery/config registration, `config.json`, templates, helpers, tests and browser access. Preserve signal handling, stdout JSONL/stderr diagnostics and hook naming. Explain WHY complex code is needed. Declare dependencies with the existing `#!/usr/bin/env -S abxpkg run --script --deps-from=./config.json:required_binaries python3` header.

## Verification

Run the test suite with `uv run pytest archivebox/tests -x` and repository checks
with `uv run prek run --all-files`. For focused work, select the relevant tests.

Releases are published only by `.github/workflows/release.yml` after the complete `dev` CI workflow succeeds. Local development and deployment commands must not publish packages, images, tags, or GitHub releases.
