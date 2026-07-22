# Upgrading Versions

```bash
set -Eeuo pipefail; cd "${ARCHIVEBOX_DATA_DIR:-$PWD}"
test -f index.sqlite3

archivebox_source="${ARCHIVEBOX_PROJECT_DIR:-git+https://github.com/ArchiveBox/ArchiveBox.git@dev}"; if test -n "${RUNNER_TEMP:-}"; then export UV_TOOL_DIR="$RUNNER_TEMP/archivebox-upgrade-tool" UV_TOOL_BIN_DIR="$RUNNER_TEMP/archivebox-upgrade-tool/bin"; fi
uv tool install --python 3.13 --upgrade "$archivebox_source"
archivebox_binary="$(uv tool dir --bin)/archivebox"
"$archivebox_binary" init
"$archivebox_binary" status

```


**✅ Upgrading checklist:**

1. Find the version you want to upgrade to on https://github.com/ArchiveBox/ArchiveBox/releases
2. **Read the release notes carefully** for any instructions or extra steps around upgrading for each release you're skipping or installing
3. **Make a full backup** of your `index.sqlite3` and `archive/` content before upgrading!  
`gzip -9 < index.sqlite3 > "index.sqlite3.$(date +%s).bak"`
4. Follow the steps below depending on your setup to run `archivebox init` (repeating as necessary for each major version if upgrading across multiple major versions)
5. Confirm the upgrade succeeded and check for any orphan/corrupted snapshots with `archivebox status`

💬 [Open an issue](https://github.com/ArchiveBox/ArchiveBox/issues/new/choose) in our bug tracker if you experience any problems with upgrading/merging/modifying collections.

---

*Note: It's recommended to only upgrade one major version at a time. e.g. if you're on `v0.4.14`, upgrade to `v0.5.6` next, then `v0.6.3`, and finally `v0.7.1` (as 3 separate steps).
You can specify exact versions with uv like so: `uv tool install --python 3.13 --upgrade archivebox==0.6.3` or with docker `docker pull archivebox/archivebox:0.6.3`. Upgrading directly across multiple major versions may work in some cases, but is not recommended for maximum data safety.*


---

**ℹ️ How it works internally:**

The same command is used for initializing a new archive and upgrading an existing one. `archivebox init` is idempotent and safely be run multiple times. Running it will ensure your collection is on the latest version and all the files are in their correct locations. `archivebox status` can be used to check for orphan/corrupted snapshots or invalid index data.

There are three main areas on disk that ArchiveBox modifies during upgrades:
- `index.sqlite3` contains the SQLite3 DB index that gets upgraded automatically by Django based on the changes in [`archivebox/core/models.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/core/models.py).
- `archive/*/index.json` these files are redundant json exports of the data for each Snapshot in `index.sqlite3`, these files are overwritten on every `archivebox update` run or anytime the Snapshot is modified from the GUI or CLI. These files will be [lazily updated](https://github.com/ArchiveBox/ArchiveBox/issues/962) to the latest schema versions as ArchiveBox accesses them, but are usually not modified in bulk during `archivebox init` when upgrading.
- `archive/*` the Snapshot output files may be moved or renamed by future upgrades (so far they have remained unchanged since v0.1, but future versions reserve the right to change their locations)

The `ArchiveBox.conf` file is not modified by upgrades and should remain forward-compatible across future versions (even when config options are renamed, we check the old names internally to maintain compatibility).

As of v0.4 and above, ArchiveBox uses the Django migrations system for deterministic, atomic, safe upgrades, so your DB should always be left in a consistent state in the event of a failure or power outage. If you need help fixing a corrupted collection, open an issue using the link above.

More info:
- https://docs.djangoproject.com/en/4.0/topics/migrations/
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#database-migrations-errors-or-upgrade-issues
- https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting

---

### Upgrading with Docker Compose ⭐️

Using Docker Compose is recommended because it makes upgrading a breeze! ✨  
Pulling and running the latest version automatically upgrades the ArchiveBox collection and all of ArchiveBox's internal dependencies.

```bash
set -Eeuo pipefail; compose_file="$(mktemp)"; docker_data="$(mktemp -d)"; if test -n "${CI:-}"; then docker tag archivebox-docs-ci archivebox/archivebox:dev; fi
printf 'services:\n  archivebox:\n    image: archivebox/archivebox:dev\n    volumes:\n      - %s:/data\n' "$docker_data" > "$compose_file"
docker compose -f "$compose_file" down; if test -n "${CI:-}"; then docker image inspect archivebox/archivebox:dev >/dev/null; else docker compose -f "$compose_file" pull; fi
docker compose -f "$compose_file" run --rm archivebox init
docker compose -f "$compose_file" up -d; container_id="$(docker compose -f "$compose_file" ps -q --status running archivebox)"; test -n "$container_id"; docker compose -f "$compose_file" down
```

More info:
- https://github.com/ArchiveBox/ArchiveBox#%EF%B8%8F-easy-setup
- https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#docker-compose
- https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#setup

### Upgrading with plain Docker

Upgrading with plain Docker is similar to the process with Docker Compose, but you have to run `archivebox init` manually at the end to finish the process.

```bash
set -Eeuo pipefail; docker_data="$(mktemp -d)"; if test -n "${CI:-}"; then docker tag archivebox-docs-ci archivebox/archivebox:dev; fi
docker image inspect archivebox/archivebox:dev >/dev/null
docker run --rm -v "$docker_data:/data" archivebox/archivebox:dev init
container_id="$(docker run --rm -d -v "$docker_data:/data" archivebox/archivebox:dev server 0.0.0.0:8000)"
test -n "$container_id"; docker inspect --format '{{.State.Running}}' "$container_id" | grep -Fx true
docker kill "$container_id"
docker run --rm -v "$docker_data:/data" archivebox/archivebox:dev init
docker run --rm -v "$docker_data:/data" archivebox/archivebox:dev server --help
```

More info:
- https://github.com/ArchiveBox/ArchiveBox#%EF%B8%8F-easy-setup
- https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#docker
- https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#setup-1

### Upgrading with a package manager

Package manager releases take a lot of effort to maintain ([contributions welcome!](https://github.com/ArchiveBox/ArchiveBox/wiki/Donations)) and sometimes lag behind the Docker releases. We make a best effort to have the latest release available through all channels within a reasonable timeframe.

Use the same package manager you originally used to install ArchiveBox. For a `uv` installation:

```bash
set -Eeuo pipefail
cd "${ARCHIVEBOX_DATA_DIR:-$PWD}"
test -f index.sqlite3
archivebox_source="${ARCHIVEBOX_PROJECT_DIR:-git+https://github.com/ArchiveBox/ArchiveBox.git@dev}"
if test -n "${RUNNER_TEMP:-}"; then export UV_TOOL_DIR="$RUNNER_TEMP/archivebox-upgrade-tool" UV_TOOL_BIN_DIR="$RUNNER_TEMP/archivebox-upgrade-tool/bin"; fi
uv tool install --python 3.13 --upgrade "$archivebox_source"
archivebox_binary="$(uv tool dir --bin)/archivebox"
"$archivebox_binary" init
"$archivebox_binary" install
"$archivebox_binary" update --index-only
"$archivebox_binary" status
```

For the Debian package, run `sudo apt update` followed by `sudo apt install --only-upgrade archivebox`. The optional auto-installer can be updated by running `curl -sSL 'https://get.archivebox.io' | sh`. Do not mix package managers for the same installation.

More info:
- https://github.com/ArchiveBox/ArchiveBox#-package-manager-setup
- https://github.com/ArchiveBox/ArchiveBox/wiki/Install#manual-setup
- https://github.com/ArchiveBox/pip-archivebox
- https://github.com/ArchiveBox/homebrew-archivebox
- https://github.com/ArchiveBox/docker-archivebox
- https://github.com/ArchiveBox/debian-archivebox
- https://github.com/ArchiveBox/electron-archivebox
- https://aur.archlinux.org/packages/archivebox
- https://github.com/NixOS/nixpkgs/blob/master/pkgs/applications/misc/archivebox/default.nix

<hr/>

## Merge two or more existing archives

See [[Merging Collections]]...

<br/>

<hr/>

## Related Documents

- https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#database
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#disk-layout
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#large-archives
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#output-folder
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#python-shell-usage
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#sql-shell-usage
