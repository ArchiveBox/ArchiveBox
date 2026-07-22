# Troubleshooting

▶️ *If you need help or have a question, you can open an [issue](https://github.com/ArchiveBox/ArchiveBox/issues?q=is%3Aissue+is%3Aopen+sort%3Aupdated-desc) or reach out on [Twitter](https://twitter.com/theSquashSH).*

What are you having an issue with?:

- [Installing ArchiveBox](#Installing)
- [Upgrading ArchiveBox](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives)
- [Configuring ArchiveBox](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration)
- [Archiving content with ArchiveBox](#Archiving)
- [Hosting your collection publicly](#Hosting-the-Archive)
- [Database and filesystem issues](#database)

---

## Installing

If using `archivebox` without Docker, make sure you've followed the full guide in the [[Install]] instructions first.  Then check here for help depending on what component you need help with.

Then make sure `archivebox` is installed available in your `$PATH`.
```bash
set -Eeuo pipefail; if command -v apt >/dev/null; then apt show archivebox || test "$?" -eq 100; fi
if command -v brew >/dev/null; then brew info archivebox/archivebox/archivebox || test "$?" -eq 1; fi
uv tool list

printf '%s\n' "$PATH"
type -a archivebox
```
**⭐️ Show the full archivebox version info + info about all installed dependencies:**
```bash
archivebox version       # shows lots of useful info about installed dependencies and more
```
(ensure the version shown is the most recent available from [Releases](https://github.com/ArchiveBox/ArchiveBox/releases))

### macOS
ArchiveBox can be installed with Homebrew or `uv` on macOS:
```bash
set -Eeuo pipefail
brew tap archivebox/archivebox
brew install archivebox; archivebox_binary="$(brew --prefix archivebox/archivebox/archivebox)/bin/archivebox"; test -x "$archivebox_binary"
data_dir="$(mktemp -d)"; trap 'rm -rf "$data_dir"' EXIT
mkdir -p "$data_dir"
cd "$data_dir"
"$archivebox_binary" init
"$archivebox_binary" install
```
More info: https://github.com/ArchiveBox/homebrew-archivebox

### Python

Make sure you have at least Python 3.13 installed on your system.

```bash
set -Eeuo pipefail; uv --version
uv python find 3.13
uv run --no-project --python 3.13 python --version
```

If you still need help getting Python installed, [the official Python docs](https://docs.python.org/3.9/using/unix.html) are a good place to start.

### Chromium/Google Chrome

For more info, see the [[Chromium Install]] page.

ArchiveBox depends on being able to access a `chromium`/`google-chrome` executable.  The executable used
defaults to `chromium` but can be manually specified with the environment variable [`CHROME_BINARY`](https://archivebox.github.io/abx-plugins/#chrome):

```bash
set -Eeuo pipefail; eval "$(uv run abxpkg env chromium --install --lib "$ABXPKG_LIB_DIR" --binproviders env,playwright,puppeteer --min-version 111 --postinstall-scripts)"; chrome_binary="$(command -v chromium)"; test -x "$chrome_binary"; env CHROME_BINARY="$chrome_binary" archivebox version
```

1. Test to make sure you have Chrome on your `$PATH` with:

```bash
set -Eeuo pipefail; eval "$(uv run abxpkg env chromium --install --lib "$ABXPKG_LIB_DIR" --binproviders env,playwright,puppeteer --min-version 111 --postinstall-scripts)"; chrome_binary="$(command -v chromium)"; test -x "$chrome_binary"; printf '%s\n' "$chrome_binary"
```
If no executable is displayed, follow the setup instructions to install and link one of them.

2. If a path is displayed, the next step is to check that it's runnable:

```bash
set -Eeuo pipefail; eval "$(uv run abxpkg env chromium --install --lib "$ABXPKG_LIB_DIR" --binproviders env,playwright,puppeteer --min-version 111 --postinstall-scripts)"; chrome_binary="$(command -v chromium)"; test -x "$chrome_binary"; "$chrome_binary" --version
```
If no version is displayed, try the setup instructions again, or confirm that you have permission to access chrome.

3. If a version is displayed and it's `<111`, upgrade it:

```bash
set -Eeuo pipefail; eval "$(uv run abxpkg env chromium --install --lib "$ABXPKG_LIB_DIR" --binproviders env,playwright,puppeteer --min-version 111 --postinstall-scripts)"
chrome_binary="$(command -v chromium)"; test -x "$chrome_binary"
chrome_major="$("$chrome_binary" --version | sed -E 's/[^0-9]*([0-9]+).*/\1/')"; test "$chrome_major" -ge 111
```

4. If a version is displayed and it's `>=111`, make sure ArchiveBox is running the right one:

```bash
set -Eeuo pipefail; eval "$(uv run abxpkg env chromium --install --lib "$ABXPKG_LIB_DIR" --binproviders env,playwright,puppeteer --min-version 111 --postinstall-scripts)"; chrome_binary="$(command -v chromium)"; test -x "$chrome_binary"; env CHROME_BINARY="$chrome_binary" archivebox version
```


### Wget & Curl

If you're missing `wget` or `curl`, simply install them using `apt` or your package manager of choice.
See the "Manual Setup" instructions for more details.

If wget times out or randomly fails to download some sites that you have confirmed are online,
upgrade wget to the most recent version with `brew upgrade wget` or `apt upgrade wget`.  There is
a bug in versions `<=1.19.1_1` that caused wget to fail for perfectly valid sites.

### NPM Dependencies

NPM packages like `readability`, `singlefile`, etc. are auto-installed by `archivebox install`.

Make sure you have installed NodeJS + NPM first, here are their [official install docs](https://nodejs.org/en/download/package-manager/).

```bash
set -Eeuo pipefail
test -f index.sqlite3
archivebox install node
uv run abxpkg env node npm --install --lib "$ABXPKG_LIB_DIR" --binproviders env,npm >/dev/null
node_binary="$ABXPKG_LIB_DIR/env/bin/node"
npm_binary="$ABXPKG_LIB_DIR/env/bin/npm"
test -x "$node_binary"
test -x "$npm_binary"
"$node_binary" --version
"$npm_binary" --version
archivebox version
```

---

## Archiving

### No links parsed from export file

Please open an [issue](https://github.com/ArchiveBox/ArchiveBox/issues) with a description of where you got the export, and
preferably your export file attached (you can redact the links).  We'll fix the parser to support your format.

### Lots of skipped sites

If you ran the archiver once, it wont re-download sites subsequent times, it will only download new links.
If you haven't already run it, make sure you have a working internet connection and that the parsed URLs look correct.
You can check the ArchiveBox stdout logs or the Web UI to see what links it's downloading.

If you're still having issues, try deleting or moving the `./archive` folder (back it up first!) and running `archivebox init` again.

### Lots of errors

Make sure you have all the dependencies installed and that you're able to visit the links from your browser normally.
Open an [issue](https://github.com/ArchiveBox/ArchiveBox/issues) with a description of the errors if you're still having problems.

### Lots of broken links from the index

Not all sites can be effectively archived with each method, that's why it's best to use a combination of `wget`, PDFs, and screenshots.
If it seems like more than 10-20% of sites in the archive are broken, open an [issue](https://github.com/ArchiveBox/ArchiveBox/issues)
with some of the URLs that failed to be archived and I'll investigate.

### Removing unwanted links from the index

`archivebox remove --help`

## Hosting the Archive

If you're having issues trying to host the archive via nginx, make sure you already have nginx running with SSL.
If you don't, google around, there are plenty of tutorials to help get that set up.  Open an [issue](https://github.com/ArchiveBox/ArchiveBox/issues)
if you have problem with a particular nginx config.

### Other database or filesystem issues

#### Docker Permissions issues

Make sure the mounted data directory is writable by the user that owns it. The `archivebox` username only exists inside the Docker container, so on the host you should check numeric ownership instead. For a new or root-owned Docker data directory, make sure it is writable by UID/GID `911:911`.

Try using [`bindfs`](https://github.com/clecherbauer/docker-volume-bindfs) to work around issues by remapping permissions, for example to remap `uid:33 gid:33` on the host to `911:911` inside the container:
`docker-compose.yml`:
```yaml
services:
  archivebox:
    volumes:
      - archivebox-data:/data

volumes:
  archivebox-data:
    driver: lebokus/bindfs:latest
    driver_opts:
      sourcePath: "${EXTERNAL_MOUNT_PARENT}/external-parent/external/archivebox"
      map: "33/911:@33/@911"
```

<br/>

---

<br/>

## Database

Database and filesystem issues are uncommon but do come up from time to time (especially when using networked storage, large archives, or multiple ArchiveBox processes for a single collection).  

*ℹ️ Generally, these commands can help you resolve most issues:*
```bash
set -Eeuo pipefail
archivebox init                 # upgrade the archivebox collection
archivebox install wget         # upgrade a runtime dependency through the normal installer
archivebox update --index-only  # force an upgrade of some of the archivebox index/collection files
archivebox server --debug --help
archivebox shell --help
uv run abxpkg env sqlite3 --install --lib "$ABXPKG_LIB_DIR" --binproviders env,apt,brew >/dev/null
"$ABXPKG_LIB_DIR/env/bin/sqlite3" --version
```

Don't be scared by the volume of content here. Almost all of these issues linked below are duplicates or old resolved bugs, but they contain valuable context and troubleshooting steps if you're trying to figure out the cause of a problem with your setup.

#### Filesystem doesn't support FSYNC (e.g. network mounts)

The `index.sqlite3` file must be stored on a filesystem that supports FSYNC (most local filesystems) in order to ensure SQLite3 database integrity when multiple ArchiveBox processes may be accessing it simultaneously. However, the `./archive` folder can be on a NAS or other filesystem that does not support FSYNC.

- [Archivebox hangs when initializing collection on network drive that doesn't support FSYNC #742](https://github.com/ArchiveBox/ArchiveBox/issues/742)
- [Question: How to run AB on localhost but store data on NAS? #894](https://github.com/ArchiveBox/ArchiveBox/issues/894)
- [Question: Docker on Windows archiving to an SMB path that doesn't support FSYNC #722](https://github.com/ArchiveBox/ArchiveBox/issues/722)
- [Support for network drives or filesystems that don't implement FSYNC #456](https://github.com/ArchiveBox/ArchiveBox/issues/456)

More info:
- https://www.geeksforgeeks.org/python-os-fsync-method/
- https://man7.org/linux/man-pages/man2/fdatasync.2.html
- https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html
- https://eclecticlight.co/2022/02/18/how-can-you-trust-a-disk-to-write-data/

#### Database and filesystem contention issues when running multiple ArchiveBox processes

ArchiveBox can sometimes struggle when archiving many links in parallel with multiple ArchiveBox processes trying to write to the database at the same time, leading to errors like this:
```bash
error='Unable to create the django_migrations table (database is locked)'
printf '%s\n' "$error" | grep -F 'database is locked'
```

These errors can also be encountered when there are permissions, network, or filesystem issues preventing writes to `index.sqlite3`.

- [Question: Unable to create the django_migrations table (database is locked) - When OUTPUT_DIR to SAMBA share #946](https://github.com/ArchiveBox/ArchiveBox/issues/946)
- [Question: ...Unable to create the django_migrations table (database is locked) #880](https://github.com/ArchiveBox/ArchiveBox/issues/880)
- [Database is locked and other weird behavior when doing simultaneous adds #781](https://github.com/ArchiveBox/ArchiveBox/issues/781)
- [Bugfix: Retry on "database locked" error (or add support for PostgreSQL/MySQL DB backend) #601](https://github.com/ArchiveBox/ArchiveBox/issues/601)
- [Architecture: Use multiple cores to run link archiving in parallel #91](https://github.com/ArchiveBox/ArchiveBox/issues/91)
- [ArchiveBox index corruption when running multiple import processes on v0.5.0 #454](https://github.com/ArchiveBox/ArchiveBox/issues/454)
- [Architecture: Concurrent runs accidentally delete each other's temp files, leaving the index broken #234](https://github.com/ArchiveBox/ArchiveBox/issues/234)
- [Database is locked and other weird behavior when doing simultaneous adds #781](https://github.com/ArchiveBox/ArchiveBox/issues/781)
- [Bugfix: Retry on "database locked" error (or add support for PostgreSQL/MySQL DB backend) #601](https://github.com/ArchiveBox/ArchiveBox/issues/601)

More info:
- https://www.sqlite.org/lockingv3.html
- https://charlesleifer.com/blog/going-fast-with-sqlite-and-python/
- https://victoria.dev/blog/sqlite-in-production-with-wal/
- https://code.djangoproject.com/ticket/29280
- https://stackoverflow.com/questions/47761570/how-can-i-avoid-database-is-locked-sqlite3-errors-in-django

#### Database migrations errors or upgrade issues

Migration or upgrade issues happen occasionally with some niche setups or when skipping major versions during archiving.  
Always backup your archive before upgrading, but know that migrations are deterministic and atomic using Django's migration system, so a failed migration does not mean your archive is unrecoverable, you just have to downgrade to the previous stable major version then continue upgrading.

```bash
archivebox init  # this usually applies any necessary migrations (atomically and indempotently, safe to run multiple times)
```

- [Bug: NOT NULL constraint failed: core_archiveresult.output when upgrading v0.4.24 archive to v0.6 #705](https://github.com/ArchiveBox/ArchiveBox/issues/705)
- [Bugfix: sqlite3.IntegrityError: NOT NULL constraint failed: core_archiveresult.cmd_version and .output #597](https://github.com/ArchiveBox/ArchiveBox/issues/597)
- [Error: django.db.utils.IntegrityError: UNIQUE constraint failed: core_tag.slug  #596](https://github.com/ArchiveBox/ArchiveBox/issues/596)
- [Bugfix: django.db.utils.IntegrityError: UNIQUE constraint failed: core_snapshot.timestamp #412](https://github.com/ArchiveBox/ArchiveBox/issues/412)
- [Best Practices for Backup/Restore #341](https://github.com/ArchiveBox/ArchiveBox/issues/341)
- [Bug: Running archivebox update --index-only doesn't upgrade Snapshot index.{html,json} files #962](https://github.com/ArchiveBox/ArchiveBox/issues/962)
- [Feature Request: Deduplicate files on archives #704](https://github.com/ArchiveBox/ArchiveBox/issues/704)

More info:
- https://docs.djangoproject.com/en/4.0/topics/migrations/
- https://realpython.com/django-migrations-a-primer/
- https://realpython.com/digging-deeper-into-migrations/
- https://www.kite.com/blog/python/django-database-migrations-overview/
- https://markusholtermann.eu/2021/06/writing-safe-database-migrations-in-django/


#### Repairing a corrupted SQLite3 database file

A corrupted database file can theoretically only happen if an external process or filesystem error corrupts the SQLite3 database (there have only been [two](https://github.com/ArchiveBox/ArchiveBox/issues/1699) [reports](https://github.com/ArchiveBox/ArchiveBox/issues/955) of a user encountering this in real life). If you ever need to repair a corrupted ArchiveBox index you can run the following steps.

Note this is specific to this error, these steps do not apply to other migrations/db errors (see above/below for other issues):
```bash
error='sqlite3.DatabaseError: database disk image is malformed'
printf '%s\n' "$error" | grep -F 'database disk image is malformed'
```

Generally all index issues should be fixable by running `archivebox init`.  
You can see the status of Snapshots and find any invalid/orphan/missing snapshots with `archivebox status`.

**Error output:**

```text
[i] [2022-03-24 20:37:27] ArchiveBox v0.6.2: archivebox init                                                                                                                                  
    > /data                                                                                                                                                                                   
                                                                                                                                                                                              
[^] Verifying and updating existing ArchiveBox collection to v0.6.2...                                                                                                                        
----------------------------------------------------------------------                                                                                                                        
                                                                                                                                                                                              
[*] Verifying archive folder structure...                                                                                                                                                     
    + ./archive, ./sources, ./logs...                                                                                                                                                         
    + ./ArchiveBox.conf...                                                                                                                                                                    
                                                                                                                                                                                              
[*] Verifying main SQL index and running any migrations needed...                                                                                                                             
Traceback (most recent call last):                                                                                                                                                            
  File "/usr/local/lib/python3.9/site-packages/django/db/backends/utils.py", line 82, in _execute                                                                                             
    return self.cursor.execute(sql)                                                                                                                                                           
  File "/usr/local/lib/python3.9/site-packages/django/db/backends/sqlite3/base.py", line 411, in execute                                                                                      
    return Database.Cursor.execute(self, query)                                                                                                                                               
sqlite3.DatabaseError: database disk image is malformed    
```

**Steps to fix:**

```bash
set -Eeuo pipefail
test -s index.sqlite3
test ! -e corrupt_index.sqlite3
test ! -e repaired_index.sqlite3
uv run abxpkg env sqlite3 --install --lib "$ABXPKG_LIB_DIR" --binproviders env,apt,brew >/dev/null
sqlite3_binary="$ABXPKG_LIB_DIR/env/bin/sqlite3"; test -x "$sqlite3_binary"
echo '.dump' | "$sqlite3_binary" index.sqlite3 | "$sqlite3_binary" repaired_index.sqlite3
"$sqlite3_binary" repaired_index.sqlite3 'PRAGMA integrity_check;' | grep -Fx ok
mv index.sqlite3 corrupt_index.sqlite3
mv repaired_index.sqlite3 index.sqlite3
"$sqlite3_binary" index.sqlite3 'PRAGMA integrity_check;' | grep -Fx ok
```

More info:
- https://github.com/ArchiveBox/ArchiveBox/issues/955 and https://github.com/ArchiveBox/ArchiveBox/issues/1699
- https://stackoverflow.com/questions/5274202/sqlite3-database-or-disk-is-full-the-database-disk-image-is-malformed


---

See here for more info:

- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading
- https://github.com/ArchiveBox/ArchiveBox/wiki/Merging-Collections
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#python-shell-usage
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#sql-shell-usage
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#do-not-run-as-root
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#output-folder
