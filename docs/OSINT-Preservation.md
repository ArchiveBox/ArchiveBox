# OSINT preservation and verification

Use a copied collection to rehearse upgrades and retain the original backup. A successful capture, an intact file hash, an authenticated response, and an independently verified timestamp establish different facts.

## Private collection configuration

From the collection directory, set these before adding investigation targets:

```console
archivebox config --set ARCHIVEDOTORG_ENABLED=False PERMISSIONS=private
archivebox config --get ARCHIVEDOTORG_ENABLED PERMISSIONS
```

For Docker, prefix these commands with `docker compose run --rm archivebox`. If Compose also sets these environment variables, update it and recreate the container: environment values can override the file. Check the effective configuration inside the running container too. Per-crawl options can change plugin selection; inspect them before submitting a target.

`ARCHIVEDOTORG_ENABLED` defaults to `True` and submits URLs to the public Wayback Machine. `PERMISSIONS=private` restricts local snapshot access; it does not disable external submissions. `SAVE_ARCHIVEDOTORG` remains a supported legacy alias. `SAVE_ARCHIVE_DOT_ORG` is a typo and has no effect. Current development builds warn about this specific typo at startup without changing the setting or printing its value.

Legacy `PUBLIC_INDEX` and `PUBLIC_SNAPSHOTS` are translated when `PERMISSIONS` is absent. Prefer an explicit `PERMISSIONS` setting for new deployments. It supplies the default for new captures; audit existing snapshots separately.

For a single hostname behind a reverse proxy, configure the public URL and replay mode:

```console
archivebox config --set BASE_URL=https://archive.example.org SERVER_SECURITY_MODE=safe-onedomain-nojsreplay
```

Host and CSRF settings are derived from these inputs. Old `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` values may help infer the URL during migration, but do not act as direct Django overrides. Single-domain safe mode disables archived JavaScript. Full JavaScript replay needs the separate origins, DNS, and TLS described in [Security Overview](Security-Overview).

## Administrator login

For unattended account creation, Django expects `DJANGO_SUPERUSER_PASSWORD` in the management command's environment. A successful `createsuperuser --noinput` without that variable can create an account with an unusable password. For example, with the password already set securely in the calling shell:

```console
docker compose run --rm -e DJANGO_SUPERUSER_PASSWORD archivebox manage createsuperuser --noinput --username analyst --email analyst@example.org
```

For an interactive reset, keep a terminal attached:

```console
docker compose exec archivebox archivebox manage changepassword analyst
```

Do not add `-T` to that interactive command. If login still fails, check the exact username, account flags, request hostname, cookie behavior, and server logs. A 403 CSRF error and the form's invalid-credentials error have different causes. `RemoteUserBackend` appearing before `ModelBackend` does not itself disable password login. With an empty `REVERSE_PROXY_WHITELIST`, ArchiveBox ignores the remote-user header. Enable proxy authentication only for the actual trusted proxy network.

## Repeated captures and upgrades

Use [Changedetection integration](Change-Detection) with `"only_new": false` for a new capture on every notification. Verify two distinct snapshot IDs, directories, and saved outputs after two submissions. Do not infer completed preservation from HTTP 200 or a queued crawl.

An in-place 0.7 upgrade is supported. Follow [Upgrading](Upgrading) on a backup copy first, compare record counts, and open both snapshot details and their raw HTML, screenshot, and PDF links. Existing timestamp URLs should resolve through the compatibility routes. Keep the original collection until the copied upgrade passes your checks. There is no need to discard old evidence solely to get the newer layout.

## Verify the evidence

The hashes plugin is enabled by default. TLSNotary and OpenTimestamps are bundled but opt-in, and either can fail independently of other capture plugins. Verify the actual plugin result and saved files for each snapshot. A sealed crawl is not proof that every plugin succeeded.

### File integrity

The hashes plugin records each listed file's SHA-256 and size in `hashes/hashes.json`, alongside a Merkle root. To check a saved file manually, calculate its digest with `sha256sum path/to/file` (Linux) or `shasum -a 256 path/to/file` (macOS) and compare it with that file's entry in the original manifest. Unlisted files are not covered. Preserve the original manifest with the evidence; rerunning the hashes hook generates a replacement rather than verifying the old one.

Matching hashes establish consistency with the manifest, not authenticity, capture time, or immutable storage. Someone who replaces both files and manifest can make them agree again. Keep a manifest digest independently or validate a corresponding signed/timestamped commitment.

### Authenticated response

Enable `TLSNOTARY_ENABLED=True` explicitly when required, and ensure the plugin produces a successful result. Its current output includes `tlsnotary/receipt.json`, `response.http`, and `metadata.json`. The installed preview checks the signature and commitment before displaying authenticated response text. For third-party review, obtain verifier code and the trusted signing key independently; follow the [TLSNotary verification instructions](https://github.com/ArchiveBox/abx-plugins/blob/main/abx_plugins/plugins/tlsnotary/README.md#output-and-verification).

The attestation covers the selected main response, not every screenshot, asset, or DOM output. The signer and its clock are trusted. It does not establish the truth of the page's claims, and is not an independent Bitcoin timestamp. Legacy proof formats need their matching verifier; absence of a current signed receipt must not be presented as a successful verification.

### Independent timestamp

Enable `OPENTIMESTAMPS_ENABLED=True` with hashes enabled. A successful submission creates `opentimestamps/hashes.json.ots` for the exact manifest bytes. The initial proof may be pending; local submission metadata and the preview's digest checks do not establish Bitcoin confirmation.

Work on a copy of the proof and its matching `hashes.json`:

```console
ots info hashes.json.ots
ots upgrade hashes.json.ots
ots verify hashes.json.ots
```

Install the upstream client with `uv tool install opentimestamps-client`. Verification normally needs access to a Bitcoin node. Preserve the original proof before upgrading the copy. Pending or unverifiable proofs must remain labeled as such. A confirmed proof establishes that the committed bytes existed by the verified block time, not the exact moment of capture. See the [OpenTimestamps plugin guide](https://github.com/ArchiveBox/abx-plugins/blob/main/abx_plugins/plugins/opentimestamps/README.md#outputs-and-verification).

## Logged-in sources and growing archives

Create a dedicated browser identity, sign in to the source, sync it with the ArchiveBox extension into a named persona, then choose that persona for the crawl or API `persona` field. Test one document and inspect its saved content before enabling recurring captures. Session expiry, access restrictions, or authentication challenges can yield a login page instead of the intended document. Persona cookies are credentials; keep the collection and backups private. See [browser persona setup](Chromium-Install).

Use [Setting Up Storage](Setting-Up-Storage) for capacity planning. Keep SQLite and active runtime state on a local filesystem. An object-storage mount does not automatically implement safe cold-data tiering or preserve all filesystem semantics. Copy and verify snapshot contents and proof files before changing storage paths; retain the source until restoration and replay are proven. Do not move the database onto an rclone/NFS/SMB mount.
