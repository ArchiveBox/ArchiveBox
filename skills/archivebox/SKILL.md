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
uv tool install archivebox
mkdir -p ~/archivebox/data
cd ~/archivebox/data
archivebox init --install
archivebox add 'https://example.com'
archivebox server 0.0.0.0:8000
```

Alternative install methods:

- Docker Compose / Docker
- Homebrew
- Debian package
- pip

## Basic Usage

Run from inside an initialized data dir:

```bash
archivebox version
archivebox status
archivebox install
archivebox add 'https://example.com'
archivebox add --extract=title,screenshot,pdf 'https://example.com'
archivebox list --json --with-headers
archivebox search 'example'
archivebox update --filter-type=domain example.com
archivebox remove --filter-type=exact 'https://example.com'
archivebox run
```

## Verification

```console
uv run pytest archivebox/tests/test_cli_add.py -q
uv run prek run --all-files
```

Use the full release/deploy loop only when requested:

```console
./bin/release_dev_stack.sh
```
