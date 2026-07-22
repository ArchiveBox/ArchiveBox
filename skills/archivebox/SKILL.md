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
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"
uv sync --project "$project_dir" --dev --all-extras
cd "$archivebox_data" && uv run --project "$project_dir" --no-sync archivebox init --install
```

## User-Facing Setup

Recommended CLI install:

```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
tool_root="$(mktemp -d)"; export UV_TOOL_DIR="$tool_root/tools" UV_TOOL_BIN_DIR="$tool_root/bin"
uv tool install --force "$project_dir"
export PLUGINS=parse_txt_urls
archivebox_data="$(mktemp -d)"
cd "$archivebox_data" && "$UV_TOOL_BIN_DIR/archivebox" init --install && "$UV_TOOL_BIN_DIR/archivebox" add --plugins=parse_txt_urls "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}"
```

Alternative install methods:

- Docker Compose / Docker
- Homebrew
- Debian package
- pip

## Basic Usage

Run from inside an initialized data dir:

<!--pytest-codeblocks:cont-->
```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"
cd "$archivebox_data" && uv run --project "$project_dir" --no-sync archivebox init --install
uv run --project "$project_dir" --no-sync archivebox version && uv run --project "$project_dir" --no-sync archivebox status && uv run --project "$project_dir" --no-sync archivebox install
uv run --project "$project_dir" --no-sync archivebox add --plugins=parse_txt_urls "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/docs-basic-usage}"
uv run --project "$project_dir" --no-sync archivebox list --json --with-headers
uv run --project "$project_dir" --no-sync archivebox search 'example' && uv run --project "$project_dir" --no-sync archivebox update --filter-type=domain example.com
uv run --project "$project_dir" --no-sync archivebox remove --yes --delete --filter-type=exact "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/docs-basic-usage}"
uv run --project "$project_dir" --no-sync archivebox run
```

## Verification

```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-.}"
uv run --project "$project_dir" --no-sync pytest "$project_dir/archivebox/tests/test_cli_add.py::test_add_help_shows_depth_and_tag_options" -q
(cd "$project_dir" && uv run --no-sync prek run --all-files)
```

Releases are published only by `.github/workflows/release.yml` after the complete `dev` CI workflow succeeds. Local development and deployment commands must not publish packages, images, tags, or GitHub releases.
