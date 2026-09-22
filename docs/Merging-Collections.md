# Merging Collections

Copy snapshot directories into the destination collection, then explicitly rescan them. Ordinary `archivebox init` and `archivebox update` intentionally avoid discovering current-layout orphan directories: that would make every startup/update scan the entire collection.

1. Back up both collections and finish active captures before copying. Upgrade legacy collections using the normal [[Upgrading]] instructions.
2. Initialize the destination collection with `archivebox init`.
3. Copy or drag the contents of each source `archive/` into the destination `archive/`, preserving the `users/<username>/snapshots/<date>/<domain>/<uuid>/` hierarchy and every snapshot's `index.jsonl`. Inspect collisions; do not overwrite different files at the same path. Do not replace the destination SQLite database.
4. From the destination data directory, run:

```bash
archivebox init
archivebox update --rescan --migrate-only --index-only
archivebox status
```

With Docker Compose:

```bash
docker compose run --rm archivebox init
docker compose run --rm archivebox update --rescan --migrate-only --index-only
docker compose run --rm archivebox status
```

`--rescan` deliberately performs an O(N) scan of snapshot directories. It imports sealed orphan snapshots, restores missing archive-result records and tags, and repairs missing metadata files and crawl links for known snapshots. It does not recover missing payload bytes or guess the identity of malformed metadata. Unresolved directories are reported, retained in place, and cause a nonzero exit status. Real legacy `archive/<timestamp>/` directories still use the existing filesystem migration flow.

The scan preserves Snapshot, Crawl, and ArchiveResult IDs and the timestamps present in their metadata. ID/URL/timestamp conflicts are reported rather than assigned replacement IDs. Existing destination records take precedence over imported metadata. Missing owners are created as inactive accounts, without importing passwords or granting administrator privileges. Older metadata without permissions imports privately; exports without Crawl records or creation timestamps cannot reproduce those missing fields exactly. Machine-local processes, credentials, schedules, and full user accounts are not synchronized.

Stop with Ctrl+C and rerun the same command to resume. There is no checkpoint file or new database state: each successful record is durable, and the scan compares existing IDs/results/tags/links before doing repair work. It discovers orphans before repairing known snapshots, with newest date/UUID names first in each group. Completed imports move to the known group on restart. Add `--reverse` to process oldest first instead. Known snapshot asset checks reuse the existing output manifest scanner. A restart still enumerates directories and reads metadata to find incomplete work; timestamps alone cannot prove completeness because copied files may retain old dates. Filters, `--resume`, and `--continuous` cannot be combined with `--rescan`.

`--rescan` discovers filesystem-only snapshots and implies filesystem maintenance without new captures. `--migrate-only` eagerly finishes pending migrations for known database snapshots; ordinary updates leave them lazy. `--index-only` checks known snapshots, rebuilds output metadata, and backfills missing search indexes from archived content. All three explicit modes default to newest first; `--reverse` flips the order. `archivebox update --rescan` is enough when search backfill is unnecessary.

For shared remote mounts, first make sure newly written objects have uploaded and the destination's directory cache can see them. Sharing `archive/` does not synchronize independent databases automatically. Confirm imported entries and representative archived files before removing any source or backup copies.

---

## Modify the ArchiveBox SQLite3 DB directly

If you need to automate changes to the ArchiveBox DB (for example adding a User from an Ansible script), you can modify the SQLite3 DB directly.

Note, this is often unnecessary for modifying ArchiveBox on a host that doesn't have the CLI installed, as you can also copy the `index.sqlite3` to a local machine that has it, do the modifications locally, then copy the modified db back into place on the host. (Docker/CLI/GUI/Web ArchiveBox all share the same DB schema/format)

```bash
cd ~/archivebox/data    # cd into your archivebox collection dir
sqlite3 index.sqlite3   # open the db with sqlite3 shell
```

#### Example: Modifying an existing user's email

```sql
UPDATE auth_user
SET email = 'someNewEmail@example.com', is_superuser = 1
WHERE username = 'someUsernameHere';
```

#### Example: Adding a new user with a hashed password

*Note: this is just an example to demonstrate direct database usage. For initial setup, open the Admin UI and create the first admin there.*

1. First, generate the hashed password in a Python shell using Django's `make_password` function.

Use the Django version bundled with the ArchiveBox installation that owns the collection:
  ```bash
  archivebox shell -c "from django.contrib.auth.hashers import make_password; print(make_password('somePasswordHere', 'someSaltHere', 'pbkdf2_sha256'))"
  ```
```python3
>>> from django.contrib.auth.hashers import make_password
>>> make_password('somePasswordHere', 'someSaltHere', 'pbkdf2_sha256')         # choose a password and a salt (can be anything 12 chars long)
'pbkdf2_sha256$...$someSaltHere$...'
```
2. Use the generated hashed password to insert a new User row in the SQLite3 database directly:
  ```bash
cd ~/archivebox/data    # cd into your archivebox collection dir
sqlite3 index.sqlite3   # open the db with sqlite3 shell
```
```sql
INSERT INTO "auth_user" ("password", "last_login", "is_superuser", "username", "first_name", "last_name", "email", "is_staff", "is_active", "date_joined")
VALUES ('GENERATED_PASSWORD_HASH', NULL, 0, 'someUsername', '', '', 'someEmail@example.com', 0, 1, '2022-03-22 23:34:02.333042')
```
  Replace the values above with the desired username, email, and password hash from python output^.

3. Log in using the new generated user to confirm it works
    http://admin.archivebox.localhost:5797/admin/login/ user: `someUsername` pass:`somePasswordHere`

More info:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#python-shell-usage
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#sql-shell-usage

---

## Database Troubleshooting

See here [Troubleshooting: Database](https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#database)...

---

## Related Documents

- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#disk-layout
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#large-archives
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#output-folder
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#python-shell-usage
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#sql-shell-usage
