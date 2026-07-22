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
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"
uv sync --project "$project_dir" --dev --all-extras
cd "$archivebox_data" && uv run --project "$project_dir" --no-sync archivebox init --install
```

Run collection commands from inside an initialized data directory:

```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"
cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init --install && uv run --project "$project_dir" --no-sync archivebox status && uv run --project "$project_dir" --no-sync archivebox add --plugins=parse_txt_urls "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}" && uv run --project "$project_dir" --no-sync archivebox run
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

<!--pytest-codeblocks:cont-->
```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"
cd "$archivebox_data" && uv run --project "$project_dir" --no-sync archivebox init --install
uv run --project "$project_dir" --no-sync archivebox version && uv run --project "$project_dir" --no-sync archivebox help && uv run --project "$project_dir" --no-sync archivebox status
uv run --project "$project_dir" --no-sync archivebox install
uv run --project "$project_dir" --no-sync archivebox add --plugins=parse_txt_urls "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/docs-basic-usage}"
uv run --project "$project_dir" --no-sync archivebox list --json --with-headers
uv run --project "$project_dir" --no-sync archivebox search 'example' && uv run --project "$project_dir" --no-sync archivebox update --filter-type=domain example.com
uv run --project "$project_dir" --no-sync archivebox remove --yes --delete --filter-type=exact "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/docs-basic-usage}"
uv run --project "$project_dir" --no-sync archivebox run
```

## Verification

Use targeted tests for focused work:

```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-.}"
uv run --project "$project_dir" --no-sync pytest "$project_dir/archivebox/tests/test_cli_add.py::test_add_help_shows_depth_and_tag_options" -q
(cd "$project_dir" && uv run --no-sync prek run --all-files)
```

Use the full release/deploy loop only when requested:

```console
./bin/release_dev_stack.sh
```
