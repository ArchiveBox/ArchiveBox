# Merging Collections

Current ArchiveBox collections cannot be merged safely by copying their `archive/users/...` trees: the database owns the Crawl, Snapshot, user, permission, and state-machine records, and `archivebox init` intentionally does not import orphaned current-layout directories. For current collections, use a database-aware migration or export the source URLs and re-archive them into the destination collection. Copying current Snapshot directories alone is a backup operation, not a merge.

The workflow below is retained for **legacy collections whose real Snapshot directories are `archive/<timestamp>/`**. `archivebox update` can import those legacy directories into a fresh index.

> [!WARNING]
> Back up every collection before merging. Confirm that the source entries are real legacy timestamp directories containing data, and inspect path conflicts instead of allowing one collection to overwrite another.

1. Upgrade both old collections to the most recent ArchiveBox version (following instructions above)
  ```bash
  cd /path/to/archivebox1/data
  archivebox init
  archivebox status

  cd /path/to/archivebox2/data
  archivebox init
  archivebox status

  # ... repeat the same for each collection if merging more than two
  ```

2. Create a new empty archivebox collection in a new folder somewhere, this will hold the new merged collection
  ```bash
  mkdir -p /path/to/archivebox_new/data
  cd /path/to/archivebox_new/data
  archivebox init
  ```

3. Copy the real legacy `archive/<timestamp>/` directories from each old collection into the new collection's `archive/` folder.
  ```bash
  rsync --archive --info=progress2 /path/to/archivebox1/data/archive/ /path/to/archivebox_new/data/archive/
  rsync --archive --info=progress2 /path/to/archivebox2/data/archive/ /path/to/archivebox_new/data/archive/
  # ...repeat the same for each collection if merging more than two
  ```

4. Run `archivebox update` in the new collection to import the legacy directories
  ```bash
  cd /path/to/archivebox_new/data
  archivebox update
  ```

5. The new collection should now contain all the entries from the old collections combined
  ```bash
  cd /path/to/archivebox_new/data
  archivebox status

  # optionally force an update of the snapshot index files (normally done lazily)
  archivebox update --index-only
  ```
  For more information about why Snapshot index files are usually updated lazily, see: https://github.com/ArchiveBox/ArchiveBox/issues/962

After you've confirmed your Snapshots are present in the new index, the old `index.sqlite3`, `index.json`, `index.html`, etc. main index files from the old archives can be safely deleted. You can optionally merge the contents of `ArchiveBox.conf` (your ArchiveBox config options), `sources/` (copies of all URLs imported in their original format), `logs/` (ArchiveBox error logs and debug info), and other root-level items yourself if that data is important to you.

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
    http://admin.archivebox.localhost:8000/admin/login/ user: `someUsername` pass:`somePasswordHere`

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
