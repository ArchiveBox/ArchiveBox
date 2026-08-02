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
apt show archivebox      # show info about the apt-installed version of archivebox
brew info archivebox     # show info about the brew-installed version of archivebox
uv tool list             # show info about uv-installed tools

echo $PATH               # show the directories your system is searching for binaries
type -a archivebox       # show all installed archivebox binaries available
```
**⭐️ Show the full archivebox version info + info about all installed dependencies:**
```bash
archivebox version       # shows lots of useful info about installed dependencies and more
```
(ensure the version shown is the most recent available from [Releases](https://github.com/ArchiveBox/ArchiveBox/releases))

### macOS
ArchiveBox can be installed with Homebrew or `uv` on macOS:
```bash
brew tap archivebox/archivebox
brew trust archivebox/archivebox
brew install archivebox

mkdir -p ~/archivebox/data
cd ~/archivebox/data     # (for example, can be anywhere)

archivebox init
archivebox install       # finish installing runtime dependencies
```
More info: https://github.com/ArchiveBox/homebrew-archivebox

### Python and uv

ArchiveBox's supported bare-metal install uses `uv`, which manages the Python 3.13 environment for the tool:

```bash
uv --version
uv tool list
archivebox version
```

If `archivebox` is missing, repeat the `uv tool install` command from the [[Install]] guide.

### Chromium/Google Chrome

For more info, see the [[Chromium Install]] page.

ArchiveBox resolves Chrome through `abxpkg`, preferring a compatible browser already installed on the host and otherwise installing a managed build:

```bash
archivebox install chrome
archivebox version
```

The version output shows the selected provider, version, and projected path. If it reports an incompatible host browser, update that browser or let ArchiveBox install the managed fallback; do not bypass the resolver with an unrelated path.


### Wget & Curl

Resolve or update both tools through the same installer:

```bash
archivebox install wget curl
archivebox version
```

### NPM Dependencies

Node.js and JavaScript extractor packages such as `readability` and `singlefile` are resolved through `abxpkg`; they do not require a separate global npm setup.

```bash
cd ~/archivebox/data   # go into your data directory
archivebox install node singlefile readability
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

To intentionally capture an already indexed URL again, use `archivebox add --no-only-new URL`. Do not delete or move the `archive/` tree to work around `ONLY_NEW`; that separates database state from its Snapshot files.

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

Make sure the mounted data directory is writable by its intended non-root owner. The current Docker entrypoint detects the first non-root collection owner and runs ArchiveBox with matching numeric UID/GID; a new root-owned collection falls back to the image's `archivebox` user. Check the host directory's numeric ownership and the entrypoint's startup output before changing permissions.

<br/>

---

<br/>

## Database

Database and filesystem issues are uncommon but do come up from time to time (especially when using networked storage, large archives, or multiple ArchiveBox processes for a single collection).  

*ℹ️ Generally, these commands can help you resolve most issues:*
```bash
archivebox init                 # upgrade the archivebox collection
archivebox install              # upgrade the archivebox runtime dependencies
archivebox update --migrate-only  # migrate/reconcile Snapshot files and metadata
archivebox server --debug       # run the server with more verbose debug log output
archivebox shell                # access the Python API / Django management shell
sqlite3 index.sqlite3           # access the SQLite3 SQL database shell
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
Unable to create the django_migrations table (database is locked)
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
sqlite3.DatabaseError: database disk image is malformed
```

Generally all index issues should be fixable by running `archivebox init`.  
You can see the status of Snapshots and find any invalid/orphan/missing snapshots with `archivebox status`.

**Error output:**

```python3
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
cd ~/archivebox/data
echo '.dump' | sqlite3 index.sqlite3 | sqlite3 repaired_index.sqlite3
mv index.sqlite3 corrupt_index.sqlite3
mv repaired_index.sqlite3 index.sqlite3
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
