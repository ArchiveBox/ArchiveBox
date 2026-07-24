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
uv run --project .. archivebox init --install
```

## User-Facing Setup

Recommended CLI install:

```bash
uv tool install --python 3.13 --prerelease allow archivebox
mkdir -p ~/archivebox/data
cd ~/archivebox/data
archivebox init --install
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

## Verification

```bash
uv run pytest archivebox/tests/test_cli_add.py::test_add_help_shows_depth_and_tag_options -q
uv run prek run --all-files
```

Releases are published only by `.github/workflows/release.yml` after the complete `dev` CI workflow succeeds. Local development and deployment commands must not publish packages, images, tags, or GitHub releases.
