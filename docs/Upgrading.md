# Upgrading Versions

```bash
# Stop any running ArchiveBox server/workers first (Ctrl+C, or stop the service/process manager that started them)

# Back up the entire collection, including index.sqlite3, ArchiveBox.conf, and all archived outputs
cd ~/archivebox
tar -czf "archivebox-data-$(date +%s).tar.gz" data/

# Update ArchiveBox using the package manager you originally installed it with
uv tool install --python 3.13 --prerelease explicit --upgrade 'archivebox>=0.9.0rc0,<0.10'
# or: sudo apt update && sudo apt install --only-upgrade archivebox
# or: brew update && brew upgrade archivebox

cd data
archivebox init
archivebox install
archivebox update --migrate-only
archivebox status

# Docker Compose install
cd ~/archivebox
docker compose down
docker compose pull
docker compose run --rm archivebox init
docker compose run --rm archivebox install
docker compose run --rm archivebox update --migrate-only
docker compose up -d
```


**✅ Upgrading checklist:**

1. Find the version you want to upgrade to on https://github.com/ArchiveBox/ArchiveBox/releases
2. **Read the release notes carefully** for any instructions or extra steps around upgrading for each release you're skipping or installing
3. **Stop any running ArchiveBox server, scheduler, and worker processes**, then back up the entire collection data directory before upgrading. `archivebox config --get ...` and a database-only backup do not include archived outputs.
   `cd ~/archivebox && tar -czf "archivebox-data-$(date +%s).tar.gz" data/`
4. Follow the steps below for your installation method, then run `archivebox init`, `archivebox install`, and `archivebox update --migrate-only` inside the collection
5. Confirm the upgrade succeeded and check for any orphan/corrupted snapshots with `archivebox status`

💬 [Open an issue](https://github.com/ArchiveBox/ArchiveBox/issues/new/choose) in our bug tracker if you experience any problems with upgrading/merging/modifying collections.

---

*Note: It's recommended to only upgrade one major version at a time. Follow each intermediate release's upgrade instructions and Python requirements rather than installing old releases with the current Python version. Upgrading directly across multiple major versions may work in some cases, but is not recommended for maximum data safety.*


---

**ℹ️ How it works internally:**

The same command is used for initializing a new archive and upgrading an existing database. `archivebox init` is idempotent and can safely be run multiple times; it applies database migrations and prepares collection-level state. `archivebox install` resolves runtime dependencies for the new version. `archivebox update --migrate-only` performs filesystem migrations and reconciles Snapshot metadata with the current layout without scheduling normal archive maintenance jobs. `archivebox status` checks collection health afterward.

There are three main areas on disk that ArchiveBox modifies during upgrades:
- `index.sqlite3` contains the SQLite3 DB index that gets upgraded automatically by Django based on the changes in [`archivebox/core/models.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/core/models.py).
- `archive/users/<user>/snapshots/<date>/<domain>/<uuid>/index.jsonl` stores per-Snapshot metadata alongside plugin-namespaced output. `archivebox update --migrate-only` may rewrite metadata, migrate older layouts, and remove obsolete timestamp projections after verified migration.
- Snapshot output directories and plugin paths can move as filesystem schemas evolve, so the entire `archive/` tree must be backed up with the database.

`ArchiveBox.conf` is migrated through the normal config loader/writer when options are renamed or normalized. Back it up with the rest of the collection and review release notes for config changes.

As of v0.4 and above, ArchiveBox uses the Django migrations system for deterministic, atomic, safe upgrades, so your DB should always be left in a consistent state in the event of a failure or power outage. If you need help fixing a corrupted collection, open an issue using the link above.

More info:
- https://docs.djangoproject.com/en/4.0/topics/migrations/
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#database-migrations-errors-or-upgrade-issues
- https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting

---

### Upgrading with Docker Compose ⭐️

Using Docker Compose keeps the image and migration commands consistent across upgrades.

```bash
cd ~/archivebox        # or wherever your folder containing docker-compose.yml is
docker compose down    # stop the currently running ArchiveBox containers
docker compose pull    # pull the latest image version from Docker Hub
docker compose run --rm archivebox init
docker compose run --rm archivebox install
docker compose run --rm archivebox update --migrate-only
docker compose up -d
```

More info:
- https://github.com/ArchiveBox/ArchiveBox#%EF%B8%8F-easy-setup
- https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#docker-compose
- https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#setup

### Upgrading with plain Docker

Upgrading with plain Docker is similar to the process with Docker Compose, but each command must mount the existing collection directory.

```bash
docker ps -a -q  --filter ancestor=archivebox/archivebox  # find any currently running archivebox containers
docker stop CONTAINER_ID

cd ~/archivebox/data  # or wherever your existing collection is stored
docker pull archivebox/archivebox:dev
docker run --rm -v $PWD:/data -it archivebox/archivebox:dev init
docker run --rm -v $PWD:/data -it archivebox/archivebox:dev install
docker run --rm -v $PWD:/data -it archivebox/archivebox:dev update --migrate-only

# restart the archivebox server container if needed
docker run -v $PWD:/data -it -p 8000:8000 archivebox/archivebox:dev server 0.0.0.0:8000
```

More info:
- https://github.com/ArchiveBox/ArchiveBox#%EF%B8%8F-easy-setup
- https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#docker
- https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#setup-1

### Upgrading with a package manager

Package manager releases take a lot of effort to maintain ([contributions welcome!](https://github.com/ArchiveBox/ArchiveBox/wiki/Donations)) and sometimes lag behind the Docker releases. We make a best effort to have the latest release available through all channels within a reasonable timeframe.

```bash
cd ~/archivebox/data   # or wherever your data folder is

# upgrade ArchiveBox using the package manager you originally used to install it
uv tool install --python 3.13 --prerelease explicit --upgrade 'archivebox>=0.9.0rc0,<0.10'
```

Or, for apt:

```bash
cd ~/archivebox/data   # or wherever your data folder is
sudo apt update
sudo apt install --only-upgrade archivebox
```

Or, for Homebrew:

```bash
cd ~/archivebox/data   # or wherever your data folder is
brew update
brew upgrade archivebox
```

Then finish the collection upgrade:

```bash
archivebox init        # run init to upgrade the collection to the latest version
archivebox install     # refresh runtime dependencies if needed

archivebox update --migrate-only  # migrate/reconcile Snapshot files and metadata

archivebox status      # check that everything succeeded
```

More info:
- https://github.com/ArchiveBox/ArchiveBox#-package-manager-setup
- https://github.com/ArchiveBox/ArchiveBox/wiki/Install#manual-setup
- https://github.com/ArchiveBox/homebrew-archivebox
- https://github.com/ArchiveBox/debian-archivebox
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
