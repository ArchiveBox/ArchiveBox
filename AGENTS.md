# ArchiveBox Agent Guide

ArchiveBox is the full self-hosted web archiving app. Keep this repo on the `dev` branch.

## Shared Standards

- Use `uv` and `uv run` for Python commands. Do not use system `python`, direct `.venv/bin/python`, or `pip` commands.
- Prefer existing repo patterns, helper APIs, fixtures, scripts, and command surfaces.
- Keep edits focused and minimal. Do not add wrappers, shims, aliases, or extra abstraction layers unless the current code path requires them.
- Do not weaken assertions, skip tests, xfail tests, or accept flaky behavior.
- No mocks, monkeypatches, fakes, simulated handlers, fake binaries, fake hooks, fake buses, or direct shortcuts around user-facing flows.
- Tests and verification should use real CLI commands, REST/API calls, browser UI flows, real hooks, real installs, real subprocesses, real DB rows, real files, and existing fixtures.
- Assertions must verify real correctness: exit codes, returned values, DB state, filesystem contents, field values, rendered output, and side effects.
- Start behavior fixes with a red failing test when a test is requested or practical.
- Trace root causes from observed behavior. Do not paper over failures with retries, wider timeouts, broad fallbacks, or looser assertions.
- Read `README.md` for the full setup, CLI, Docker, API, and release surface.

## Development Setup

```bash
uv sync --dev --all-extras
mkdir -p data
cd data
uv run --project .. archivebox init --install
```

Run collection commands from inside an initialized data directory:

```bash
cd data
uv run --project .. archivebox status
uv run --project .. archivebox add 'https://example.com'
uv run --project .. archivebox run
```

## User-Facing Setup

Recommended CLI install:

```bash
uv tool install --force .
export PLUGINS=parse_txt_urls
archivebox_data="$(mktemp -d)"
cd "$archivebox_data"
archivebox init --install
archivebox add --plugins=parse_txt_urls 'https://example.com'
```

Alternative install methods:

- Docker Compose / Docker
- Homebrew
- Debian package
- pip

## Basic Usage

<!--pytest-codeblocks:cont-->
```bash
archivebox version
archivebox help
archivebox status
archivebox install
archivebox add --plugins=parse_txt_urls 'https://example.com/docs-basic-usage'
archivebox list --json --with-headers
archivebox search 'example'
archivebox update --filter-type=domain example.com
archivebox remove --filter-type=exact 'https://example.com'
archivebox run
```

## Verification

Use targeted tests for focused work:

```bash
uv run pytest archivebox/tests/test_cli_add.py::test_add_help_shows_depth_and_tag_options -q
uv run prek run --all-files
```

Use the full release/deploy loop only when requested:

```console
./bin/release_dev_stack.sh
```
