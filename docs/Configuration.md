# Configuration

Configuration of ArchiveBox is done by using the `archivebox config` command, modifying the `ArchiveBox.conf` file in the data folder, or by setting environment variables as process defaults. All three methods work in Docker as well.

*Some equivalent examples of setting some configuration options:*
```bash
archivebox config --set TIMEOUT=120
# OR edit ArchiveBox.conf and add this under its existing [ARCHIVING_CONFIG] section:
TIMEOUT=120
# OR
env TIMEOUT=120 archivebox add ~/Downloads/bookmarks_export.html
```

Environment variables seed process-level defaults. Persisted Machine, Persona, Crawl, and Snapshot settings can override them depending on scope, and existing Crawl config is not silently overwritten by later environment changes. Runtime-derived values like crawl/snapshot output dirs are resolved fresh for each run instead of being stored in frozen crawl config. For more examples see [Usage: Configuration](Usage#run-archivebox-with-configuration-options)...

<br/>

<img src="https://imgur.zervice.io/EUeQbiZ.png" width="200px" align="right"/>

**Available Configuration Options:**
 - [General Settings:](#general-settings) Archiving process, output format, crawl limits, and retention.
 - [Server Settings:](#server-settings) Web UI, authentication, subdomain routing, and reverse proxy options.
 - [Storage Settings:](#storage-settings) File layout, permissions, and temp/lib directories.
 - [Database Settings:](#database-settings) SQLite tuning and lock-retry behavior.
 - [Search Settings:](#search-settings) Full-text search backend selection.
 - [Shell Options:](#shell-options) Format & behavior of CLI output.
 - [Plugin Configuration:](#plugin-configuration) Per-plugin options (now documented separately).

<br/>

---

<img src="https://imgur.zervice.io/iTYT7Ip.png" width="100%"/>
<p align="center">
<i>In case this document is ever out of date, check the source code for config definitions: <a href="https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/config/common.py"><code>archivebox/config/common.py</code></a> ➡️</i>
</p>

## General Settings

*General options around the archiving process, output format, retention, and concurrency limits.*

---
#### `ONLY_NEW`
**Possible Values:** [`True`]/`False`
Controls what happens when you `add` a URL that **already has a Snapshot** in your index.

- **`True`** (default) — skip the URL entirely. No new Snapshot is created, no extractors run. The existing Snapshot is left exactly as-is.
- **`False`** — create a **new** Snapshot for the URL (separate UUID, separate output directory) and run every enabled extractor on it. The previously archived Snapshot is preserved untouched; you end up with two side-by-side captures of the same URL.

Equivalent to the `--only-new` / `--no-only-new` flag on `archivebox add`:

```bash
archivebox add https://example.com                    # honors ONLY_NEW (default True)
archivebox add --no-only-new https://example.com      # force a re-archive even if already in the index
```

> [!NOTE]
> Setting `ONLY_NEW=False` (or `--no-only-new`) is the supported way to **re-capture a page that has changed since your last archive** — for example, archiving a news article, then re-archiving it later after the article was edited. Each re-archive becomes its own Snapshot row with its own timestamp.

> [!NOTE]
> Within a single crawl, URLs are deduplicated regardless of `ONLY_NEW` — submitting the same URL twice in one `add` invocation still produces only one Snapshot. `ONLY_NEW` only governs deduplication *against the existing index*.

*Related options:*
[`DEFAULT_PERSONA`](#default_persona), [`URL_DENYLIST`](#url_denylist), [`URL_ALLOWLIST`](#url_allowlist)

---
#### `TIMEOUT`
**Possible Values:** [`60`]/`120`/...
Maximum allowed runtime **per-extractor, per-Snapshot** in seconds. If you have a slow network connection or are seeing frequent timeout errors, you can raise this value.

This is a *plugin-shared* setting — each individual extractor can override it with its own `<EXTRACTOR>_TIMEOUT` (e.g. [`WGET_TIMEOUT`](https://archivebox.github.io/abx-plugins/#wget), [`CHROME_TIMEOUT`](https://archivebox.github.io/abx-plugins/#chrome), [`YTDLP_TIMEOUT`](https://archivebox.github.io/abx-plugins/#ytdlp)). See the [per-plugin docs](https://archivebox.github.io/abx-plugins/) for the full list.

> [!NOTE]
> `TIMEOUT` only caps a single extractor invocation. To bound the *total* wall-clock runtime of an entire crawl, use [`CRAWL_TIMEOUT`](#crawl_timeout) instead.

> [!WARNING]
> Do not set this to anything less than `5` seconds — Chrome will hang indefinitely and many sites will fail completely. Anywhere between `30` and `3000` is the recommended range.

*Related options:*
[`CRAWL_TIMEOUT`](#crawl_timeout), [`CRAWL_MAX_URLS`](#crawl_max_urls), [`SNAPSHOT_MAX_SIZE`](#snapshot_max_size)

---
#### `RESOLUTION`
**Possible Values:** [`1440,2000`]/`1024,768`/...
Default screenshot/PDF viewport resolution in `width,height` pixels. Used as the fallback for `SCREENSHOT_RESOLUTION`, `PDF_RESOLUTION`, and `CHROME_RESOLUTION`.

This is a *plugin-shared* setting — individual extractors override it via `<EXTRACTOR>_RESOLUTION` (e.g. [`SCREENSHOT_RESOLUTION`](https://archivebox.github.io/abx-plugins/#screenshot), [`PDF_RESOLUTION`](https://archivebox.github.io/abx-plugins/#pdf), [`CHROME_RESOLUTION`](https://archivebox.github.io/abx-plugins/#chrome)). See the [per-plugin docs](https://archivebox.github.io/abx-plugins/) for plugin-specific overrides.

---
#### `CHECK_SSL_VALIDITY`
**Possible Values:** [`True`]/`False`
Whether to enforce HTTPS certificate validity and HSTS chain of trust when archiving sites. Set this to `False` if you want to archive pages even if they have expired or invalid certificates.

This is a *plugin-shared* setting — every HTTP-fetching extractor ([`wget`](https://archivebox.github.io/abx-plugins/#wget), [`yt-dlp`](https://archivebox.github.io/abx-plugins/#ytdlp), [`gallery-dl`](https://archivebox.github.io/abx-plugins/#gallerydl), [`chrome`](https://archivebox.github.io/abx-plugins/#chrome), etc.) honors it, and individual extractors can override with `<EXTRACTOR>_CHECK_SSL_VALIDITY`. See the [per-plugin docs](https://archivebox.github.io/abx-plugins/).

> [!WARNING]
> When `False`, ArchiveBox cannot guarantee that the captured content matches the real site — a man-in-the-middle could substitute responses. Only disable for trusted networks or for archiving legacy/internal sites with expired certs.

---
#### `USER_AGENT`
**Possible Values:** [`Mozilla/5.0 ... ArchiveBox/{VERSION} ...`]/`"Mozilla/5.0 ..."`/...
The default `User-Agent` string sent during archiving. The built-in default identifies ArchiveBox and links back to the GitHub repo so site operators can identify and contact archivers if needed.

This is a *plugin-shared* setting — each extractor ([`wget`](https://archivebox.github.io/abx-plugins/#wget), [`chrome`](https://archivebox.github.io/abx-plugins/#chrome), [`yt-dlp`](https://archivebox.github.io/abx-plugins/#ytdlp), [`singlefile`](https://archivebox.github.io/abx-plugins/#singlefile), …) can override it with its own `<EXTRACTOR>_USER_AGENT`, otherwise it falls back to this value. See the [per-plugin docs](https://archivebox.github.io/abx-plugins/) for per-extractor specifics.

> [!NOTE]
> Some sites block requests that look like bots or that don't match a real browser. If you're getting 403s or empty responses, try setting this to a current Chrome/Firefox UA string.

---
#### `COOKIES_FILE`
**Possible Values:** [`None`]/`/path/to/cookies.txt`/...

> [!TIP]
> **Prefer [personas](#default_persona) over `COOKIES_FILE` for authentication.** A persona bundles a `cookies.txt`, a Chrome user-data-dir, a user-agent, and any other per-identity state into one named profile that's swappable per-crawl and automatically scoped across every extractor. `COOKIES_FILE` (and the per-extractor `<EXTRACTOR>_COOKIES_FILE` overrides) is a low-level escape hatch for when you specifically need to point at a hand-rolled cookies file outside the persona system — most users should ignore it and configure auth through `archivebox persona create` instead.

Path to a [Netscape-format `cookies.txt`](http://www.cookiecentral.com/faq/#3.5) file passed to `wget`, `curl`, `yt-dlp`, and other non-Chrome extractors for authentication. Required when archiving sites behind a login (paywalls, social media feeds, members-only forums, etc.) **if you're not using a persona**.

This is a *plugin-shared* setting — each extractor can override it with `<EXTRACTOR>_COOKIES_FILE` (e.g. [`WGET_COOKIES_FILE`](https://archivebox.github.io/abx-plugins/#wget), [`YTDLP_COOKIES_FILE`](https://archivebox.github.io/abx-plugins/#ytdlp), [`GALLERYDL_COOKIES_FILE`](https://archivebox.github.io/abx-plugins/#gallerydl)). [Chrome](https://archivebox.github.io/abx-plugins/#chrome)-based extractors instead read auth state from the persona's `CHROME_USER_DATA_DIR`. See the [per-plugin docs](https://archivebox.github.io/abx-plugins/) for per-extractor variants.

You can generate a `cookies.txt` using a [browser extension](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc), or with `wget --save-cookies` + `--user=... --password=...`.

The recommended path is to create a persona and let it manage cookies + Chrome profile state for you:

```bash
archivebox persona create --import=chrome personal
archivebox add --persona=personal https://members.example.com/feed
```

> [!WARNING]
> **Use separate burner credentials dedicated to archiving** — don't re-use your normal daily Facebook/Instagram/Youtube/etc. account cookies as server responses often contain your name/email/PII and session tokens, which then get preserved in your snapshots forever!

*Related options:*
[`DEFAULT_PERSONA`](#default_persona), [`CHROME_USER_DATA_DIR`](https://archivebox.github.io/abx-plugins/#chrome)

---
<a id="active_persona"></a>
#### `DEFAULT_PERSONA`
**Possible Values:** [`Default`]/`personal`/`work`/...
The persona profile used when no explicit persona is selected for a new crawl. The selected persona is stored on the Crawl row; `DEFAULT_PERSONA` is not duplicated into `Crawl.config`. Personas bundle a Chrome user-data-dir, a `cookies.txt`, auth state, a user-agent, and any other per-identity config into a single named profile, letting you swap between archiving contexts (logged-out vs. signed-into-work-account vs. signed-into-personal-account) without manually juggling files.

ArchiveBox auto-creates the named persona on disk if it doesn't already exist. See the [Personas wiki page](https://github.com/ArchiveBox/ArchiveBox/wiki/Personas) for the full directory layout.

*Related options:*
[`COOKIES_FILE`](#cookies_file)

---
<a id="url_blacklist"></a>
#### `URL_DENYLIST`
**Possible Values:** [`\.(css|js|otf|ttf|woff|woff2|gstatic\.com|googleapis\.com/css)(\?.*)?$`]/`.+\.exe$`/...

Regex pattern matched against every URL discovered during a crawl. Any matching URL is **excluded** from archiving — useful for blocking tracking pixels, ad networks, CDN-hosted CSS/fonts, or arbitrary file extensions you don't want to capture.

The default skips common static assets (CSS, fonts, Google Fonts CDN) so they aren't re-fetched as separate Snapshots during recursive crawls — the parent page's `singlefile`/`dom` output already inlines them.

*Note: This option is also recognized under its legacy alias `URL_BLACKLIST`.*

*Related options:*
[`URL_ALLOWLIST`](#url_allowlist)

---
<a id="url_whitelist"></a>
#### `URL_ALLOWLIST`
**Possible Values:** [`None`]/`^http(s)?:\/\/(.+)?example\.com\/?.*$`/...

Regex pattern matched against every URL discovered during a crawl. When set, any URL that does **not** match is excluded. Useful for recursive crawling scoped to a single domain or path prefix (e.g. only follow links within `docs.example.com/v2/`).

When both are set, `URL_DENYLIST` takes precedence over `URL_ALLOWLIST`.

*Note: This option is also recognized under its legacy alias `URL_WHITELIST`.*

*Related options:*
[`URL_DENYLIST`](#url_denylist)

---
#### `TAG_SEPARATOR_PATTERN`
**Possible Values:** [`[,]`]/`[,;]`/`[,;\s]`/...
Regex character class used to split tag strings (e.g. `news,politics; longform`) into individual tags when importing URLs. The default splits on commas only; widen it if you paste in tags separated by semicolons, spaces, or other delimiters.

---
#### `CRAWL_MAX_URLS`
**Possible Values:** [`0`]/`50`/`500`/...
Maximum number of unique URLs (Snapshots) a single crawl is allowed to produce. `0` means unlimited. Counts both seed URLs you submitted and URLs discovered by recursive crawlers (`parse_dom_outlinks`, `parse_html_urls`, etc.).

Once the cap is reached, recursive crawlers stop emitting new Snapshots and the crawl is marked with `stop_reason = "crawl_max_urls"`. **Raising the cap later and re-queuing the crawl will resume discovery** — the limit state is persisted in `<crawl_dir>/.abx-dl/limits.json` and re-evaluated each tick.

> [!NOTE]
> Use this as a safety net for recursive crawls (`--depth=N`) that could otherwise blow up to thousands of pages on link-heavy sites.

*Related options:*
[`CRAWL_MAX_SIZE`](#crawl_max_size), [`CRAWL_TIMEOUT`](#crawl_timeout), [`CRAWL_MAX_CONCURRENT_SNAPSHOTS`](#crawl_max_concurrent_snapshots), [`SNAPSHOT_MAX_SIZE`](#snapshot_max_size)

---
#### `CRAWL_MAX_SIZE`
**Possible Values:** [`0`]/`50MB`/`5GB`/`104857600`/...
Maximum cumulative output size (in bytes) a single crawl is allowed to produce across all of its Snapshots. `0` means unlimited.

Accepts a raw byte count (`104857600`) or a unit-suffixed string (`100MB`, `5GB`, `1TiB`). Sizes are accumulated by the extractor service as each `ArchiveResult` writes its outputs to disk; once the cap is exceeded, in-flight Snapshots finish but no new ones are admitted and the crawl stops with `stop_reason = "crawl_max_size"`.

> [!NOTE]
> Bounds the **disk footprint** of a crawl, not the wire transfer — a 2MB HTML page can produce 50MB of screenshots, PDFs, SingleFile bundles, and media downloads, and this cap applies to the on-disk total.

*Related options:*
[`SNAPSHOT_MAX_SIZE`](#snapshot_max_size), [`CRAWL_MAX_URLS`](#crawl_max_urls), [`CRAWL_TIMEOUT`](#crawl_timeout)

---
#### `CRAWL_TIMEOUT`
**Possible Values:** [`0`]/`300`/`3600`/...
Maximum total wall-clock runtime for a single crawl in seconds. `0` means unlimited.

Distinct from [`TIMEOUT`](#timeout): `TIMEOUT` caps one extractor invocation on one Snapshot; `CRAWL_TIMEOUT` caps the *entire crawl* — all Snapshots, all extractors, all retries, all recursive discovery passes — together. Once exceeded the crawl is marked `stop_reason = "crawl_timeout"` and queued Snapshots are skipped.

> [!NOTE]
> Useful as a hard ceiling for unattended/scheduled crawls (e.g. "spend at most 1 hour archiving Hacker News tonight"). Pair with `CRAWL_MAX_URLS` and `CRAWL_MAX_SIZE` for belt-and-suspenders bounds.

*Related options:*
[`TIMEOUT`](#timeout), [`CRAWL_MAX_URLS`](#crawl_max_urls), [`CRAWL_MAX_SIZE`](#crawl_max_size)

---
#### `CRAWL_MAX_CONCURRENT_SNAPSHOTS`
**Possible Values:** [`4`]/`1`/`8`/`16`/...
How many Snapshots within a single crawl ArchiveBox will archive in parallel. The runner schedules up to this many extractor pipelines at once, then waits for one to finish before starting the next.

Raising this speeds up large crawls on beefy hardware, but each concurrent Snapshot opens a new tab inside the crawl's shared Chrome instance (when Chrome-based extractors are enabled) — RAM per tab and CPU pressure scale roughly linearly with concurrency. On a typical laptop, `2-4` is sane; on a dedicated server with 32GB+ RAM, `8-16` can be reasonable.

> [!NOTE]
> This is **per-crawl** concurrency. If you run multiple crawls simultaneously, each one independently gets up to `CRAWL_MAX_CONCURRENT_SNAPSHOTS` parallel Snapshots.

*Related options:*
[`CRAWL_MAX_URLS`](#crawl_max_urls), [`TIMEOUT`](#timeout)

---
#### `SNAPSHOT_MAX_SIZE`
**Possible Values:** [`0`]/`10MB`/`500MB`/...
Maximum cumulative output size (in bytes) **per individual Snapshot**. `0` means unlimited. Same unit-suffix parsing as `CRAWL_MAX_SIZE` (`10MB`, `2GB`, raw bytes, etc.).

Where `CRAWL_MAX_SIZE` is a *crawl-wide* budget, `SNAPSHOT_MAX_SIZE` puts a ceiling on any *one* page's output. Once a Snapshot's outputs exceed the cap, remaining extractors for that Snapshot are skipped and the Snapshot is tagged with `stop_reason = "snapshot_max_size"` — but the rest of the crawl continues normally.

> [!NOTE]
> Particularly useful when crawling sites with occasional huge pages (e.g. a forum where most threads are small but a few are 500MB media galleries) — it caps the outliers without throttling the whole crawl.

*Related options:*
[`CRAWL_MAX_SIZE`](#crawl_max_size), [`CRAWL_MAX_URLS`](#crawl_max_urls)

---
#### `DELETE_AFTER`
**Possible Values:** [`0`]/`24h`/`7d`/`4w`/`6mo`/`1y`/...
Retention policy: automatically delete Crawls, Snapshots, ArchiveResults, and Process rows (and their on-disk outputs) after this duration has elapsed. `0`, `""`, or `None` disables auto-deletion (the default — ArchiveBox never deletes anything unless you ask).

Accepted units: `h`/`hr`/`hour`, `d`/`day`, `w`/`week`, `mo`/`month`, `y`/`yr`/`year`. The minimum non-zero duration is `1h`. Examples:

```bash
archivebox config --set DELETE_AFTER=24h     # daily rolling buffer
archivebox config --set DELETE_AFTER=30d     # 30-day retention
archivebox config --set DELETE_AFTER=6mo     # 6 months
```

`DELETE_AFTER` can be set globally, per-persona, per-crawl, or per-snapshot — the most-specific value wins. When a Snapshot is created, its `delete_at` timestamp is computed from the effective `DELETE_AFTER` and persisted; the retention sweeper then deletes rows whose `delete_at` is in the past.

> [!WARNING]
> Deletion is **destructive and irreversible**. Files in the snapshot's output directory are removed from disk. Use with care on important archives — and *never* set this on the global config if you have legacy snapshots you don't want garbage-collected.

*Related options:*
[`PERMISSIONS`](#permissions)

---
<a id="public_snapshots"></a>
<a id="public_index--public_snapshots--public_add_view"></a>
#### `PERMISSIONS`
**Possible Values:** [`public`]/`unlisted`/`private`
Default visibility for newly created Snapshots. Inherited by every Snapshot in a Crawl unless explicitly overridden at the Crawl or Snapshot level.

- **`public`** — Snapshot appears in the public index *and* its content is directly accessible without login.
- **`unlisted`** — Snapshot content is accessible via direct link, but it is **not** listed in the public index. Equivalent to a "secret URL."
- **`private`** — Snapshot is hidden from the public index *and* its content requires admin login.

This option supersedes the removed `PUBLIC_SNAPSHOTS` boolean and is also driven by the still-current [`PUBLIC_INDEX`](#public_index) flag — both are interpreted as a coarse mapping onto `PERMISSIONS` for backwards compatibility (`PUBLIC_SNAPSHOTS=False` ⇒ `private`, `PUBLIC_INDEX=False` ⇒ `unlisted`, either set to `True` ⇒ `public`). Setting `PERMISSIONS` directly wins over either legacy flag.

> [!NOTE]
> `PERMISSIONS` controls **per-Snapshot** visibility. Server-wide auth (whether the whole UI requires login, whether the add-view is open) is still controlled by [`PUBLIC_INDEX`](#public_index) and [`PUBLIC_ADD_VIEW`](#public_add_view) under Server Settings.

*Related options:*
[`PUBLIC_INDEX`](#public_index), [`PUBLIC_ADD_VIEW`](#public_add_view), [`DELETE_AFTER`](#delete_after)

---
<a id="enabled_plugins"></a>
#### `PLUGINS`
**Possible Values:** [`""`]/`wget,favicon,screenshot`/`chrome,singlefile,dom`/...
Comma-separated **whitelist** of plugins to load and run for this archiving run. When empty (the default), ArchiveBox uses the installed/enabled plugin set — i.e. every plugin whose `<PLUGIN>_ENABLED` config evaluates true.

When set, only the listed plugins (plus any plugins they declare as `required_plugins` in their `config.json` — e.g. picking `singlefile` automatically pulls in `chrome`) participate in the run. Equivalent to the CLI flag:

```bash
archivebox add --plugins=wget,favicon,screenshot https://example.com
```

The admin "Add" form and REST API both write to `PLUGINS` when you select extractors — there is no separate "enabled set" config knob; `PLUGINS` is the single source of truth for which plugins run on any given Crawl, Snapshot, or Persona scope.

Useful for one-off runs ("just grab a screenshot and skip everything else") or for reproducible per-crawl pipelines stored on the Crawl row.

---

## Server Settings

*Options for the web UI, authentication, subdomain routing, and reverse proxy configuration.*

---
<a id="admin_username"></a>
<a id="admin_password"></a>
#### `ADMIN_USERNAME` / `ADMIN_PASSWORD`
**Possible Values:** [`None`]/`"admin"`/...

Used on first run / initial setup in any installation method. ArchiveBox will create an admin superuser with the specified username and password when both options are present during `archivebox init`. After the user exists, changing these values has no effect — use `archivebox manage changepassword <username>` or the Django admin UI instead.

> [!WARNING]
> Setting `ADMIN_PASSWORD` via environment variable bakes the secret into your shell history, Docker inspect output, and process listings. For long-lived deployments, set it once during provisioning, create the user, then unset the variable.

More info:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-up-Authentication

*Related options:*
[`LDAP_ENABLED`](#ldap_enabled), [`REVERSE_PROXY_USER_HEADER`](#reverse_proxy_user_header)

---
<a id="public_index"></a>
<a id="public_add_view"></a>
#### `PUBLIC_INDEX` / `PUBLIC_ADD_VIEW`
**Possible Values:** [`True`]/`False` (for `PUBLIC_INDEX`), [`False`]/`True` (for `PUBLIC_ADD_VIEW`)

Server-wide toggles for whether login is required to use each public area of ArchiveBox.

```bash
archivebox config --set PUBLIC_INDEX=True        # allow viewing the snapshot index without login
archivebox config --set PUBLIC_ADD_VIEW=False    # require login to submit new URLs via the web UI
```

- `PUBLIC_INDEX` (default `True`) — when on, anonymous visitors can browse the snapshot list page. Individual snapshot visibility is still gated by each Snapshot's own [`PERMISSIONS`](#permissions) field.
- `PUBLIC_ADD_VIEW` (default `False`) — when on, anonymous visitors can submit new URLs to be archived via the `/add` form. Leave this off on any internet-exposed instance unless you actively want a public submission endpoint.

> [!NOTE]
> **`PUBLIC_SNAPSHOTS` has been removed as a global toggle.** Snapshot visibility is now decided per-Snapshot via the [`PERMISSIONS`](#permissions) field (`public` / `unlisted` / `private`) under General Settings. The old anchors are preserved on `PERMISSIONS` so existing links keep working.

*Related options:*
[`PERMISSIONS`](#permissions), [`SERVER_SECURITY_MODE`](#server_security_mode), [`ADMIN_USERNAME`](#admin_username--admin_password)

---
#### `SECRET_KEY`
**Possible Values:** *auto-generated 50-character random string*

Django's secret key, used for cryptographic signing of sessions, CSRF tokens, password reset links, and other signed payloads. Auto-generated on first server start and persisted to `ArchiveBox.conf` so it survives restarts. If the config file isn't writable (read-only mount, mid-init race), an in-memory random key is used and all users are logged out on the next boot.

> [!WARNING]
> Treat this value like a password. Anyone with the `SECRET_KEY` can forge sessions and CSRF tokens for your instance. Don't commit `ArchiveBox.conf` to public repos, and rotate it (forcing all users to log in again) if you suspect it's been exposed.

---
#### `BIND_ADDR`
**Possible Values:** [`127.0.0.1:8000`]/`0.0.0.0:8000`/`[::]:8000`/`0.0.0.0:80`/...

The `host:port` socket the ArchiveBox web server actually listens on. **This is the local bind socket, not the public URL** — for the public URL clients see, set [`BASE_URL`](#base_url).

- `127.0.0.1:8000` (default) — listen only on the loopback interface. Safest when you're running a reverse proxy on the same host and don't want the server reachable directly from the network.
- `0.0.0.0:8000` — listen on **all** IPv4 interfaces. Required when running in Docker without `--network=host`, or when you want the server reachable from other machines on your LAN without a reverse proxy.
- `[::]:8000` — listen on all IPv6 interfaces (most modern OSes will accept v4-mapped connections too).
IPv6 literal addresses must be bracketed: `[::1]:8000`, not `::1:8000`.

> [!NOTE]
> Inside Docker, binding to `127.0.0.1` means the server is unreachable from outside the container — use `0.0.0.0:8000` and let Docker handle the port-forwarding, or publish the port with `-p 127.0.0.1:8000:8000` on the host side instead.

*Related options:*
[`BASE_URL`](#base_url), [`SERVER_SECURITY_MODE`](#server_security_mode)

---
<a id="allowed_hosts"></a>
<a id="csrf_trusted_origins"></a>
#### `BASE_URL`
**Possible Values:** [`""`]/`https://archive.example.com`/`http://archivebox.localhost:8000`/...

The canonical public URL of your ArchiveBox instance. Used to build absolute links in templates, redirects (`/admin/login/?next=...`), admin notification emails, OG/meta tags, and — in subdomain security mode — to derive the `admin.`, `web.`, `api.`, and per-snapshot `snap-<id>.` subdomains.

**When `BASE_URL` is set explicitly**, ArchiveBox treats it as the source of truth and ignores the incoming `Host` header for URL building. In `safe-subdomains-fullreplay` mode setting it is **required for redirects to work correctly**.

**When `BASE_URL` is empty**, the value is resolved at request time from the incoming request's `Host` header (with any leading `admin.` / `web.` / `api.` / `snap-*.` label stripped to recover the canonical base). Loopback hostnames (`localhost`, `127.0.0.1`, `0.0.0.0`, `::`) are rewritten to `archivebox.localhost` so subdomain routing works without `/etc/hosts` edits. If there's no live request, [`BIND_ADDR`](#bind_addr) is used as a last resort.

The scheme is taken from the explicit `BASE_URL` if set, otherwise from the request (so put a reverse proxy in front for HTTPS and trust `X-Forwarded-Proto`).

ArchiveBox automatically derives the underlying Django `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` settings from `BASE_URL` + [`SERVER_SECURITY_MODE`](#server_security_mode), so you do **not** set those directly — the system widens them as needed to admit the admin/web/api subdomains.

> [!NOTE]
> **Pin `BASE_URL` explicitly on any deployment using `safe-subdomains-fullreplay` mode.** A misconfig banner will surface in the rendered UI until you do.

> [!NOTE]
> **Legacy upgrade path (0.7.3 → 0.9):** `archivebox init` preserves the complete legacy config and migrates the old `ARCHIVE_BASE_URL`, `ADMIN_BASE_URL`, or documented `LISTEN_HOST` hostname to `BASE_URL`. A single non-default `CSRF_TRUSTED_ORIGINS` or `ALLOWED_HOSTS` entry is used as a fallback when those settings are absent. New installs should set `BASE_URL` directly; the legacy hostname settings are no longer user-settable knobs.

*Related options:*
[`SERVER_SECURITY_MODE`](#server_security_mode), [`BIND_ADDR`](#bind_addr)

---
#### `SERVER_SECURITY_MODE`
**Possible Values:** [`auto`]/`safe-subdomains-fullreplay`/`safe-onedomain-nojsreplay`/`unsafe-onedomain-noadmin`/`danger-onedomain-fullreplay`

The top-level security posture of the server. Controls how archived content is served, whether the admin/API control plane is reachable, and which host(s) the UI is split across. **This is the most important security knob** — pick the most restrictive mode that still works for your use case.

ArchiveBox splits its surfaces across three logical hosts: `admin.*` (Django admin + session cookies, the entire control plane), `web.*` (anonymous public browsing UI, optional public add view, and public snapshot index), and `api.*` (REST/JSON endpoints). In subdomain mode each gets its own host derived from [`BASE_URL`](#base_url); session/CSRF cookies are scoped to `admin.*` only, so `web.*`, `api.*`, and compromised replay pages on `snap-<id>.*` can't read admin auth.

| Mode | Host layout | JS replay | Control plane | Use when |
|---|---|---|---|---|
| **`auto`** *(default, recommended)* | Subdomains for any `*.localhost` request; otherwise one host | Full raw replay on `*.localhost`; otherwise raw archived HTML uses no-JS replay. Plugins can opt into a trusted viewer with an explicit `full.html` preview template. | Enabled | The zero-configuration default. Localhost gets the highest-fidelity isolated setup; ordinary public/LAN hostnames do not require wildcard DNS or TLS. |
| **`safe-subdomains-fullreplay`** | admin/web/api/snap-* on separate subdomains | Full JS replay enabled | Enabled on `admin.*` only | You have wildcard DNS (`*.archive.example.com`) and a TLS cert that covers it. Archived JS runs sandboxed away from the admin origin. |
| **`safe-onedomain-nojsreplay`** | Everything on one host | Raw archived HTML cannot run JS. Explicit trusted plugin preview templates can run the JS needed by their viewer. | Enabled | You can't get wildcard DNS. Trades raw replay fidelity for same-origin safety while retaining trusted viewer formats. |
| **`unsafe-onedomain-noadmin`** | Everything on one host | Full JS replay enabled | **Disabled** — `/admin`, `/accounts`, `/api`, `/add`, `/web` return 403; only GET/HEAD/OPTIONS allowed | Read-only public archive on a single host. Operate the instance via CLI only; the web admin is unreachable. |
| **`danger-onedomain-fullreplay`** | Everything on one host | Full JS replay enabled | Enabled | Local dev / trusted-network only. Archived JS runs on the **same origin as the admin UI** — a malicious archived page can call admin endpoints with your session. **Do not expose this mode to the internet.** |

SingleFile output is served as ordinary HTML in every mode; it remains usable in no-JS modes because SingleFile removes the page's scripts during capture. ArchiveWeb.page/ReplayWeb.page and MHTML use their existing trusted preview templates. ArchiveBox always attempts to load these viewers, including when the incoming request is plain HTTP, because HTTPS may be terminated by an upstream proxy. Browser service-worker rules still require ReplayWeb.page to be reached through HTTPS or localhost for replay to initialize.

> [!WARNING]
> Switching to any mode whose name starts with `unsafe-` or `danger-` is logged at startup and surfaces a banner in the UI. **Don't use these modes on a public hostname** — archived JavaScript will run on the same origin as your admin session.

> [!NOTE]
> Explicit subdomain mode requires both wildcard DNS (`*.archive.example.com`) and (if using TLS) a wildcard certificate. The default `auto` mode only selects subdomain routing for `*.localhost`, which browsers resolve locally without custom DNS or TLS setup.

> [!NOTE]
> In one-domain `auto` mode, read-only requests are accepted through any valid ingress hostname, but POST/PUT/PATCH/DELETE requests are accepted only on the canonical `BASE_URL` host. Canonical links always use `BASE_URL`. Explicit subdomain mode continues to allow state-changing requests on its derived admin/API hosts.

*Related options:*
[`BASE_URL`](#base_url), [`PERMISSIONS`](#permissions)

More info:
- [Security Overview](Security-Overview)

---
#### `SNAPSHOTS_PER_PAGE`
**Possible Values:** [`50`]/`25`/`100`/`200`/...

Number of rows to render per page on the Snapshot and ArchiveResult list views (admin index, public index, and the Django admin changelists for both models). Lower values reduce per-request render time; higher values speed up bulk browsing at the cost of heavier rendering. Must be ≥ 1.

---
#### `FOOTER_INFO`
**Possible Values:** [`Content is hosted for personal archiving purposes only.  Contact server owner for any takedown requests.`]/...

Free-form text rendered in the footer of every archive page. Useful for adding a takedown contact, an org disclaimer, or attribution. Plain text — no HTML.

---
#### `REVERSE_PROXY_USER_HEADER`
**Possible Values:** [`Remote-User`]/`X-Remote-User`/`X-Forwarded-User`/...

HTTP header your reverse proxy (Authelia, oauth2-proxy, Authentik, nginx `auth_request`, etc.) sets to the authenticated username. ArchiveBox's `ReverseProxyAuthMiddleware` reads this header **only when the request's source IP is inside [`REVERSE_PROXY_WHITELIST`](#reverse_proxy_whitelist)** — otherwise the header is ignored to prevent direct-connect spoofing.

The header name is matched case-insensitively and normalized to the `HTTP_*` form Django exposes (e.g. `Remote-User` → `HTTP_REMOTE_USER`).

*Related options:*
[`REVERSE_PROXY_WHITELIST`](#reverse_proxy_whitelist), [`LOGOUT_REDIRECT_URL`](#logout_redirect_url)

---
#### `REVERSE_PROXY_WHITELIST`
**Possible Values:** [`""`]/`172.16.0.0/16`/`10.0.0.5/32,fd00::/8`/...

Comma-separated list of IPv4 / IPv6 addresses or CIDR networks that are trusted to set [`REVERSE_PROXY_USER_HEADER`](#reverse_proxy_user_header). When empty (the default), reverse-proxy auth is **completely disabled** — the header is never consulted no matter who set it.

When non-empty, only requests whose `REMOTE_ADDR` falls inside one of the listed networks have the header honored. Anything else falls back to standard session auth. The CIDR list is validated on every request; an invalid entry raises `ImproperlyConfigured` and breaks the server, so test changes carefully.

> [!WARNING]
> **Set this to the actual IP of your reverse proxy, never `0.0.0.0/0` or a public network.** With a wide-open whitelist, anyone who can reach the server directly can forge any username they like via the header.

*Related options:*
[`REVERSE_PROXY_USER_HEADER`](#reverse_proxy_user_header), [`LOGOUT_REDIRECT_URL`](#logout_redirect_url)

---
#### `LOGOUT_REDIRECT_URL`
**Possible Values:** [`/`]/`https://example.com/some/other/app`/`/accounts/logout-landing/`/...

URL users are redirected to after logging out. The default `/` keeps users on ArchiveBox; set this to an external URL when using reverse-proxy SSO so logout terminates the upstream session too (e.g. `https://auth.example.com/logout`).

*Related options:*
[`REVERSE_PROXY_USER_HEADER`](#reverse_proxy_user_header), [`REVERSE_PROXY_WHITELIST`](#reverse_proxy_whitelist)

---

### LDAP Settings

*Options for LDAP / Active Directory authentication via [django-auth-ldap](https://github.com/django-auth-ldap/django-auth-ldap). Requires `uv tool install --python 3.13 --prerelease explicit --upgrade 'archivebox[ldap]>=0.9.0rc0,<0.10'` (which also pulls in the system `libldap` / `libsasl` headers).*

---
#### `LDAP_ENABLED`
**Possible Values:** [`False`]/`True`

Master switch for LDAP authentication. When `True`, ArchiveBox loads the `django-auth-ldap` backend and validates that `LDAP_SERVER_URI`, `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD`, and `LDAP_USER_BASE` are all set — startup fails fast otherwise.

```bash
uv tool install --python 3.13 --prerelease explicit --upgrade 'archivebox[ldap]>=0.9.0rc0,<0.10'
```

Then set these configuration values:
```yaml
LDAP_ENABLED: True
LDAP_SERVER_URI: "ldap://ldap.example.com:3389"
LDAP_BIND_DN: "ou=archivebox,ou=services,dc=ldap.example.com"
LDAP_BIND_PASSWORD: "secret-bind-user-password"
LDAP_USER_BASE: "ou=users,ou=archivebox,ou=services,dc=ldap.example.com"
LDAP_USER_FILTER: "(uid=%(user)s)"
LDAP_USERNAME_ATTR: "username"
LDAP_FIRSTNAME_ATTR: "givenName"
LDAP_LASTNAME_ATTR: "sn"
LDAP_EMAIL_ATTR: "mail"
LDAP_CREATE_SUPERUSER: False
```

More info:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-up-Authentication
- https://github.com/django-auth-ldap/django-auth-ldap#example-configuration

*Related options:*
[`ADMIN_USERNAME`](#admin_username--admin_password), [`REVERSE_PROXY_USER_HEADER`](#reverse_proxy_user_header)

---
#### `LDAP_SERVER_URI`
**Possible Values:** [`None`]/`ldap://ldap.example.com:389`/`ldaps://ldap.example.com:636`/...

URI of the LDAP server to bind against. Use `ldaps://` for TLS or `ldap://` for plaintext (plus optional StartTLS at the protocol level). Required when [`LDAP_ENABLED`](#ldap_enabled) is `True`.

---
#### `LDAP_BIND_DN`
**Possible Values:** [`None`]/`cn=archivebox,ou=services,dc=example,dc=com`/...

Distinguished name of the service account used to perform user searches. This account only needs read access to the user subtree under [`LDAP_USER_BASE`](#ldap_user_base). Required when [`LDAP_ENABLED`](#ldap_enabled) is `True`.

---
#### `LDAP_BIND_PASSWORD`
**Possible Values:** [`None`]/`<bind-service-password>`/...

Password for the [`LDAP_BIND_DN`](#ldap_bind_dn) service account. Required when [`LDAP_ENABLED`](#ldap_enabled) is `True`.

> [!WARNING]
> Treat this like any other service credential — keep it out of shell history and version control. Prefer setting it via the config file (which has owner-only permissions) over environment variables.

---
#### `LDAP_USER_BASE`
**Possible Values:** [`None`]/`ou=users,dc=example,dc=com`/...

Base DN under which to search for user entries. Required when [`LDAP_ENABLED`](#ldap_enabled) is `True`. The search is performed as `LDAP_BIND_DN` with the filter from [`LDAP_USER_FILTER`](#ldap_user_filter).

---
#### `LDAP_USER_FILTER`
**Possible Values:** [`(uid=%(user)s)`]/`(sAMAccountName=%(user)s)`/`(&(objectClass=person)(mail=%(user)s))`/...

LDAP search filter used to find a user entry at login. The literal token `%(user)s` is replaced with the username the user typed into the login form. Common values:
- `(uid=%(user)s)` — OpenLDAP-style
- `(sAMAccountName=%(user)s)` — Active Directory
- `(mail=%(user)s)` — match by email

---
#### `LDAP_USERNAME_ATTR`
**Possible Values:** [`username`]/`uid`/`sAMAccountName`/...

LDAP attribute on the user entry that becomes the local Django `username`. Must be unique within the directory.

---
#### `LDAP_FIRSTNAME_ATTR`
**Possible Values:** [`givenName`]/...

LDAP attribute mapped to Django's `User.first_name`.

---
#### `LDAP_LASTNAME_ATTR`
**Possible Values:** [`sn`]/...

LDAP attribute mapped to Django's `User.last_name`.

---
#### `LDAP_EMAIL_ATTR`
**Possible Values:** [`mail`]/`userPrincipalName`/...

LDAP attribute mapped to Django's `User.email`.

---
#### `LDAP_CREATE_SUPERUSER`
**Possible Values:** [`False`]/`True`

When `True`, every LDAP user who successfully authenticates is auto-promoted to Django superuser. **Off by default** — leave it off unless your directory's user base is already restricted to operators, since superusers can modify config, delete snapshots, and run server commands.

> [!WARNING]
> Combining `LDAP_CREATE_SUPERUSER=True` with a broad [`LDAP_USER_BASE`](#ldap_user_base) (e.g. an entire company OU) effectively grants admin to every employee. Scope the user base or use group-based access control via `django-auth-ldap`'s `AUTH_LDAP_USER_FLAGS_BY_GROUP` (configured in custom `settings.py`) instead.

---

## Storage Settings

*Options for the on-disk layout, file permissions, and temp/lib directories that ArchiveBox reads and writes during archiving.*

---
<a id="dir_output_permissions"></a>
#### `OUTPUT_PERMISSIONS`
**Possible Values:** [`644`]/`755`/...
Permissions to set on output files written into the archive directory. The directory mode is derived from this by OR-ing in the execute bits (so `644` files imply `755` dirs), which subsumes the legacy `DIR_OUTPUT_PERMISSIONS` option (formerly a separate `755`-default field) — directory mode is no longer settable on its own.

> [!NOTE]
> Set this to `600` if you want archives to be readable only by the ArchiveBox user, or `664`/`775` if you need a shared group to read/write the data dir.

*Related options:*
[`ENFORCE_ATOMIC_WRITES`](#enforce_atomic_writes)
- https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#docker-permissions-issues

---
#### `ENFORCE_ATOMIC_WRITES`
**Possible Values:** [`True`]/`False`
Whether to write output files atomically (write to a tempfile + `rename()` into place) so that a crash or `kill -9` mid-write can never leave a partial file in the archive. Disable only if you are debugging a filesystem that doesn't support atomic renames (some FUSE mounts).

---
#### `TMP_DIR`
**Possible Values:** [`data/tmp/<machine_id>`]/`/tmp/archivebox/abc5d851`/...
Path for temporary files, the supervisord unix socket, and generated supervisor config. The default is a per-machine subdirectory under the data folder (`tmp/<machine_id>`) so multiple machines sharing the same data dir (e.g., over NFS) don't collide on socket files.

> [!WARNING]
> `TMP_DIR` *must* be a short, local path readable/writable by the ArchiveBox user. Unix socket paths have a hard ~96-character limit, so a deeply nested `TMP_DIR` will silently break the supervisor. It also must live on a real local filesystem (tmpfs/SSD) — FUSE, network mounts, and Docker bind mounts on macOS often cannot host unix sockets at all (see [`ALLOW_NO_UNIX_SOCKETS`](#allow_no_unix_sockets)).

If ArchiveBox detects the configured `TMP_DIR` is unwritable or too long, it will auto-fall-back to `/tmp/archivebox/<collection_id>` at startup.

*Related options:*
[`ABXPKG_LIB_DIR`](#abxpkg_lib_dir), [`ALLOW_NO_UNIX_SOCKETS`](#allow_no_unix_sockets)

---
#### `ABXPKG_LIB_DIR`
**Possible Values:** [`<user-config>/abx/lib`]/`/opt/archivebox/lib`/`~/.config/abx/lib`/...
Path for installed binary dependencies (`chromium`, `single-file`, `yt-dlp`, `ripgrep`, etc.) managed by `abxpkg`. The default is the platform-standard user-config location (`~/.config/abx/lib` on Linux, `~/Library/Application Support/abx/lib` on macOS, `%APPDATA%\abx\lib` on Windows) so a single binary installation can be shared across multiple collections on the same machine without re-downloading.

> [!NOTE]
> `ABXPKG_LIB_DIR` can grow to several GB. Put it on a fast local disk — running extractors off a network-mounted `ABXPKG_LIB_DIR` will be painfully slow.

*Related options:*
[`TMP_DIR`](#tmp_dir)

---
<a id="lib_bin_dir"></a>
<a id="data_dir"></a>
<a id="archive_dir"></a>
<a id="users_dir"></a>
<a id="personas_dir"></a>
<a id="crawl_dir"></a>
<a id="snap_dir"></a>
#### `ALLOW_NO_UNIX_SOCKETS`
**Possible Values:** [`False`]/`True`
**Alias:** `ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS`

Skip the startup check that verifies [`TMP_DIR`](#tmp_dir) can host unix-domain sockets (a real `bind()` on a `.sock` file). Set to `True` only when running ArchiveBox on a filesystem that cannot back unix sockets — most commonly Docker Desktop on macOS with a host bind-mounted `TMP_DIR`, where the osxfs/virtiofs layer rejects `bind()` calls.

> [!WARNING]
> This disables a real safety check, not a cosmetic one. When unix sockets are unavailable some plugins that talk to long-lived helpers over `.sock` files (supervisord control socket, browser launcher RPC) may behave unpredictably. Prefer fixing [`TMP_DIR`](#tmp_dir) to point at a tmpfs/SSD inside the container; reach for `ALLOW_NO_UNIX_SOCKETS` only when that's genuinely not possible.

*Related options:*
[`TMP_DIR`](#tmp_dir)

---

## Database Settings

*Options for choosing and tuning the index database that backs ArchiveBox's snapshot, tag, and crawl metadata.*

ArchiveBox stores all of its index metadata in a single SQLite database file (`index.sqlite3` inside your data directory) by default, or optionally in a PostgreSQL database (see [`DATABASE_ENGINE`](#database_engine)). The defaults are tuned for nearly all users — the knobs below mostly govern **lock-contention behavior**, which matters when multiple workers touch the database concurrently (e.g. supervised orchestrators, parallel `archivebox add` runs, container restarts that race against an in-flight write, or long-running web/admin processes alongside CLI commands).

> [!NOTE]
> These are advanced operator tuning options. If you are not actively diagnosing `database is locked` errors or planning a non-default storage layout, you can safely leave everything in this section at its default.

*Learn more:*
- https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#sqlite-database-is-locked
- https://www.sqlite.org/wal.html
- https://www.sqlite.org/pragma.html

---
<a id="database_engine"></a>
<a id="archivebox_database_engine"></a>
#### `DATABASE_ENGINE`
**Possible Values:** [`sqlite`]/`postgres`
Which database backend to use for the main index. Settable as `ARCHIVEBOX_DATABASE_ENGINE` or under `[DATABASE_CONFIG]` in `ArchiveBox.conf`.

The default `sqlite` keeps everything in a single `index.sqlite3` file inside the data directory and requires no external services. Set this to `postgres` to store the index in a PostgreSQL database instead — useful for large collections with many concurrent writers, or when the data directory lives on a filesystem where SQLite performs poorly (e.g. network mounts).

With `postgres`, connection details come from the options below. `archivebox init` will create the configured database automatically if the server is reachable and the database does not exist yet. Only the *index* moves to PostgreSQL — snapshot output files stay in `./archive/` in the data directory, and plugin-owned sidecar databases (e.g. the `search.sqlite3` full-text index) are unaffected.

```ini
# example ArchiveBox.conf
[DATABASE_CONFIG]
DATABASE_ENGINE = postgres
DATABASE_NAME = archivebox
DATABASE_HOST = 127.0.0.1
DATABASE_PORT = 5432
DATABASE_USER = archivebox
DATABASE_PASSWORD = s3cret
```

> [!WARNING]
> Pick a backend when you first run `archivebox init` and stick with it. There is no built-in tool (yet) to move an existing collection's index between SQLite and PostgreSQL.

*Related options:*
[`DATABASE_NAME`](#database_name), [`DATABASE_HOST`](#database_host)

---
<a id="database_host"></a>
<a id="archivebox_database_host"></a>
<a id="database_port"></a>
<a id="archivebox_database_port"></a>
<a id="database_user"></a>
<a id="archivebox_database_user"></a>
<a id="database_password"></a>
<a id="archivebox_database_password"></a>
#### `DATABASE_HOST` / `DATABASE_PORT` / `DATABASE_USER` / `DATABASE_PASSWORD`
**Possible Values:** [`127.0.0.1`] / [`5432`] / [`archivebox`] / [empty]
PostgreSQL connection settings, used only when [`DATABASE_ENGINE`](#database_engine)`=postgres`. Settable as `ARCHIVEBOX_DATABASE_HOST`, `ARCHIVEBOX_DATABASE_PORT`, `ARCHIVEBOX_DATABASE_USER`, and `ARCHIVEBOX_DATABASE_PASSWORD`.

`DATABASE_HOST` may also be a path to a directory containing a PostgreSQL unix socket (e.g. `/var/run/postgresql`).

---
<a id="database_name"></a>
<a id="archivebox_database_name"></a>
#### `DATABASE_NAME`
**Possible Values:** [`index.sqlite3`] / `archivebox` / ...
The main index database. Settable as `ARCHIVEBOX_DATABASE_NAME`.

With the default [`DATABASE_ENGINE`](#database_engine)`=sqlite`, this is the path to the SQLite index file inside the data directory (`index.sqlite3`). With `DATABASE_ENGINE=postgres`, it is the name of the PostgreSQL database instead (default: `archivebox`), created automatically by `archivebox init` if it does not exist.

---
#### `SQLITE_JOURNAL_MODE`
**Possible Values:** [`WAL` on native installs]/[`DELETE` in Docker]/`TRUNCATE`/`PERSIST`/`MEMORY`/`OFF`
SQLite [journal mode](https://www.sqlite.org/pragma.html#pragma_journal_mode), applied via `PRAGMA journal_mode = ...` on every new connection. Settable as `ARCHIVEBOX_SQLITE_JOURNAL_MODE`.

The default is `WAL` (Write-Ahead Logging) on native installs and `DELETE` in Docker. WAL lets readers and a single writer operate concurrently without blocking each other, but its shared-memory locking is unsafe when a Docker bind mount exposes the same live database to host-side SQLite processes. Docker therefore rejects an explicit WAL override for the SQLite backend; use PostgreSQL for safe cross-runtime concurrency.

> [!WARNING]
> Do not change this unless you have a specific reason. `DELETE` and `TRUNCATE` serialize readers against writers. `MEMORY` and `OFF` disable durable journaling and can corrupt the database on crash or power loss. WAL requires one local filesystem and one locking domain; it is unsafe across network filesystems and Docker host bind mounts.

---
#### `SQLITE_MMAP_SIZE`
**Possible Values:** [`134217728`] (128 MiB) on bare-metal, [`0`] (disabled) inside Docker / `0` / `268435456` / ...
Maximum number of bytes of the database file SQLite is allowed to map into memory via `mmap()`, applied via `PRAGMA mmap_size = ...`. Settable as `ARCHIVEBOX_SQLITE_MMAP_SIZE`.

When mmap is enabled, SQLite reads pages directly from the OS page cache instead of issuing `read()` syscalls and copying into a userspace buffer — meaningfully faster page reads on large databases when there is RAM available to cache them. Setting this to `0` disables memory-mapped I/O entirely and falls back to regular `read()` calls.

*Note: The default is `0` (disabled) inside Docker, because the container's reported memory limits often do not reflect the host page cache and large mmap regions can interact poorly with `cgroup` accounting. On bare-metal installs the default is `134217728` (128 MiB).*

---
#### `SQLITE_BUSY_TIMEOUT`
**Possible Values:** [`30000`]/`5000`/`60000`/... (milliseconds, integer)
SQLite busy-wait timeout in **milliseconds**, applied via `PRAGMA busy_timeout = ...` on every new connection and converted to seconds for the Python `sqlite3` connection-level `timeout=` argument. Settable as `ARCHIVEBOX_SQLITE_BUSY_TIMEOUT`.

When a statement encounters a write lock, SQLite will sleep and retry internally for up to this many milliseconds before returning `SQLITE_BUSY` to the Python driver. Raise it if you see spurious lock errors under sustained write contention and you would rather block than fail; lower it if you want callers to fail fast.

---
#### `SQLITE_LOCK_RETRY_TIMEOUT`
**Possible Values:** [`60.0`]/`0`/`120.0`/... (seconds, float)
Total wall-clock budget in **seconds** that ArchiveBox's own retry loop will spend re-attempting a single locked statement before aborting it. Settable as `ARCHIVEBOX_SQLITE_LOCK_RETRY_TIMEOUT`.

When the SQLite driver eventually surfaces a `database is locked` error (after [`SQLITE_BUSY_TIMEOUT`](#sqlite_busy_timeout) has already elapsed), ArchiveBox wraps the cursor in a higher-level retry loop that logs the locking holders and re-issues the statement. This is the maximum total time spent in that outer loop, across all retries, before giving up and raising. Set to `0` to disable the cap and retry indefinitely.

> [!NOTE]
> The outer retry only applies to statements that are *not* inside an explicit `transaction.atomic()` block. Statements inside an explicit transaction propagate the error to the caller immediately, since silently retrying would re-execute statements the caller already considered committed.

*Related options:*
[`SQLITE_LOCK_RETRY_INTERVAL`](#sqlite_lock_retry_interval)

---
#### `SQLITE_LOCK_RETRY_INTERVAL`
**Possible Values:** [`5.0`]/`1.0`/`10.0`/... (seconds, float, must be `> 0`)
Sleep duration in **seconds** between successive attempts inside the ArchiveBox lock-retry loop. Settable as `ARCHIVEBOX_SQLITE_LOCK_RETRY_INTERVAL`.

Lower values retry more aggressively (useful if you expect locks to clear quickly and want to minimize end-to-end latency); higher values reduce log noise and wasted CPU when locks are typically held for a long time. Must be strictly greater than `0`.

*Related options:*
[`SQLITE_LOCK_RETRY_TIMEOUT`](#sqlite_lock_retry_timeout)

---

## Search Settings

*Options for full-text search backend configuration.*

ArchiveBox can index Snapshot text/HTML output into searchable indexes that power the search bar in the Web UI and the `archivebox search <query>` CLI command. Multiple backend engines can be enabled at once; `SEARCH_BACKEND_ENGINE` selects the default used by the UI and CLI.

> [!NOTE]
> Each backend has its own tuning knobs (e.g. [Sonic](https://archivebox.github.io/abx-plugins/#search_backend_sonic) host/port, [ripgrep](https://archivebox.github.io/abx-plugins/#search_backend_ripgrep) flags, [SQLite FTS](https://archivebox.github.io/abx-plugins/#search_backend_sqlite) database path). Those backend-specific options now live with the plugin that implements them — see the [abx-plugins docs](https://archivebox.github.io/abx-plugins/) for the full per-backend schema.

---
#### `SEARCH_BACKEND_ENGINE`
**Possible Values:** [`ripgrep`]/`sqlite`/`sonic`

Which search backend engine to use when running `archivebox search` and rendering the Web UI search bar.

- **`ripgrep`** — Pure filesystem grep across each Snapshot's archived output (HTML, text, metadata) via the [`search_backend_ripgrep`](https://archivebox.github.io/abx-plugins/#search_backend_ripgrep) plugin. No extra daemon, no extra database to maintain — just install `rg` and it works. Slow on very large collections (each query re-scans the disk) but always 100% correct: results reflect what's actually on disk *right now*, no stale index. ArchiveBox keeps it enabled as the fallback when Sonic is unavailable.

- **`sonic`** *(default)* — Fast, suggest-style fuzzy search via a running [Sonic](https://github.com/valeriansaliou/sonic) daemon (configured via the [`search_backend_sonic`](https://archivebox.github.io/abx-plugins/#search_backend_sonic) plugin). ArchiveBox pushes text into Sonic at index time and queries it at search time. Sub-millisecond queries even at very large scale; ArchiveBox starts the managed service automatically when this backend is selected.

- **`sqlite`** — FTS5 full-text index stored alongside ArchiveBox's main `index.sqlite3`, configured via the [`search_backend_sqlite`](https://archivebox.github.io/abx-plugins/#search_backend_sqlite) plugin. No extra processes, no extra binary — uses the SQLite already shipped with Python. Faster than `ripgrep` on large collections, slightly slower than `sonic`, but no daemon to babysit. Good middle ground for users who want a real index without operational overhead.

*Note: Backend-specific tuning ([Sonic](https://archivebox.github.io/abx-plugins/#search_backend_sonic) host/port/password, [ripgrep](https://archivebox.github.io/abx-plugins/#search_backend_ripgrep) flag overrides, [SQLite FTS](https://archivebox.github.io/abx-plugins/#search_backend_sqlite) database path, indexer batch size, etc.) lives in each search-backend plugin's own config schema — see the [abx-plugins docs](https://archivebox.github.io/abx-plugins/) for the full per-backend option list.*

---

## Shell Options

*Options around the format & behavior of CLI output.*

Most of the values in this section are auto-detected from your terminal at startup, but each can be overridden explicitly via env var, `ArchiveBox.conf`, or `archivebox config --set` — useful for CI logs, cron jobs, log files, and Docker stdout where the auto-detection isn't what you want.

---
#### `DEBUG`
**Possible Values:** [`False`]/`True`

Enable verbose debug mode for the entire ArchiveBox process. Automatically set to `True` when `--debug` is passed on the command line; otherwise honors the env var / config value.

When enabled this turns on:
- Full Python tracebacks (instead of the trimmed friendly version) on any error
- Django SQL query logging to stderr
- Template auto-reload (no caching) for the web UI
- Verbose plugin / hook lifecycle logging
- Extra detail in `archivebox version`, `archivebox status`, and crash reports

> [!WARNING]
> **Do not leave `DEBUG=True` enabled on a production / publicly-reachable server.** It exposes tracebacks with file paths, SQL queries, and environment details that can leak sensitive info to anyone who triggers an error page.

*Related options:* [`USE_COLOR`](#use_color), [`SHOW_PROGRESS`](#show_progress)

---
#### `USE_COLOR`
**Possible Values:** [`True` *(auto-detected)*]/`False`

Whether to colorize console output with ANSI escape codes. Defaults to `True` when stdout is a TTY (interactive terminal) and `False` otherwise.

Override to **force-off** when piping `archivebox` output into a log file or cron-mail wrapper that doesn't strip ANSI codes (otherwise you'll see `^[[31m...^[[0m` litter throughout your logs). Override to **force-on** for tools like `script(1)` or some CI runners that don't report as a TTY but *do* render ANSI correctly.

```bash
USE_COLOR=False archivebox add https://example.com >> archive.log
```

*Related options:* [`SHOW_PROGRESS`](#show_progress), [`DEBUG`](#debug)

---
#### `SHOW_PROGRESS`
**Possible Values:** [`True` *(auto-detected)*]/`False`

Whether to render live progress bars during long-running operations (archiving, indexing, migrations). Defaults to `True` when stdout is a TTY, `False` otherwise.

Override to **force-off** in environments where the auto-detection is fooled into thinking it has a TTY (some Docker setups, Kubernetes log collectors, `tmux`/`screen` pipes) but the redrawing carriage-return output ends up as garbage in your logs.

```bash
SHOW_PROGRESS=False archivebox add < urls.txt
```

*Related options:* [`USE_COLOR`](#use_color)

---

## Plugin Configuration

<!-- Backward-compatibility anchors for old links to plugin sections/options that have moved to the per-plugin documentation site. -->
<a id="2captcha-settings"></a>
<a id="accessibility-settings"></a>
<a id="accessibility_enabled"></a>
<a id="accessibility_timeout"></a>
<a id="anthropic_api_key"></a>
<a id="archive.org-settings"></a>
<a id="archivedotorg_enabled"></a>
<a id="archivedotorg_timeout"></a>
<a id="chrome-settings"></a>
<a id="chrome_args"></a>
<a id="chrome_args_extra"></a>
<a id="chrome_binary"></a>
<a id="chrome_check_ssl_validity"></a>
<a id="chrome_delay_after_load"></a>
<a id="chrome_enabled"></a>
<a id="chrome_headless"></a>
<a id="chrome_pageload_timeout"></a>
<a id="chrome_resolution"></a>
<a id="chrome_sandbox"></a>
<a id="chrome_timeout"></a>
<a id="chrome_user_agent"></a>
<a id="chrome_user_data_dir"></a>
<a id="chrome_wait_for"></a>
<a id="claude-chrome-settings"></a>
<a id="claude-code-cleanup-settings"></a>
<a id="claude-code-extract-settings"></a>
<a id="claude-code-settings"></a>
<a id="claudechrome_enabled"></a>
<a id="claudechrome_max_actions"></a>
<a id="claudechrome_model"></a>
<a id="claudechrome_prompt"></a>
<a id="claudechrome_timeout"></a>
<a id="claudecode_binary"></a>
<a id="claudecode_enabled"></a>
<a id="claudecode_max_turns"></a>
<a id="claudecode_model"></a>
<a id="claudecode_timeout"></a>
<a id="claudecodecleanup_enabled"></a>
<a id="claudecodecleanup_max_turns"></a>
<a id="claudecodecleanup_model"></a>
<a id="claudecodecleanup_prompt"></a>
<a id="claudecodecleanup_timeout"></a>
<a id="claudecodeextract_enabled"></a>
<a id="claudecodeextract_max_turns"></a>
<a id="claudecodeextract_model"></a>
<a id="claudecodeextract_prompt"></a>
<a id="claudecodeextract_timeout"></a>
<a id="console-log-settings"></a>
<a id="consolelog_enabled"></a>
<a id="consolelog_timeout"></a>
<a id="defuddle-settings"></a>
<a id="defuddle_args"></a>
<a id="defuddle_args_extra"></a>
<a id="defuddle_binary"></a>
<a id="defuddle_enabled"></a>
<a id="defuddle_timeout"></a>
<a id="dns-settings"></a>
<a id="dns_enabled"></a>
<a id="dns_timeout"></a>
<a id="dom-outlinks-parser-settings"></a>
<a id="dom-settings"></a>
<a id="dom_enabled"></a>
<a id="dom_timeout"></a>
<a id="favicon-settings"></a>
<a id="favicon_enabled"></a>
<a id="favicon_timeout"></a>
<a id="forum-dl-settings"></a>
<a id="forumdl_args"></a>
<a id="forumdl_args_extra"></a>
<a id="forumdl_binary"></a>
<a id="forumdl_enabled"></a>
<a id="forumdl_output_format"></a>
<a id="forumdl_timeout"></a>
<a id="gallery-dl-settings"></a>
<a id="gallerydl_args"></a>
<a id="gallerydl_args_extra"></a>
<a id="gallerydl_binary"></a>
<a id="gallerydl_check_ssl_validity"></a>
<a id="gallerydl_cookies_file"></a>
<a id="gallerydl_enabled"></a>
<a id="gallerydl_timeout"></a>
<a id="git-settings"></a>
<a id="git_args"></a>
<a id="git_args_extra"></a>
<a id="git_binary"></a>
<a id="git_domains"></a>
<a id="git_enabled"></a>
<a id="git_timeout"></a>
<a id="hashes-settings"></a>
<a id="hashes_enabled"></a>
<a id="hashes_timeout"></a>
<a id="headers-settings"></a>
<a id="headers_enabled"></a>
<a id="headers_timeout"></a>
<a id="html-to-text-settings"></a>
<a id="html-url-parser-settings"></a>
<a id="htmltotext_enabled"></a>
<a id="htmltotext_timeout"></a>
<a id="i-still-dont-care-about-cookies-settings"></a>
<a id="infinite-scroll-settings"></a>
<a id="infiniscroll_enabled"></a>
<a id="infiniscroll_expand_details"></a>
<a id="infiniscroll_min_height"></a>
<a id="infiniscroll_scroll_delay"></a>
<a id="infiniscroll_scroll_distance"></a>
<a id="infiniscroll_scroll_limit"></a>
<a id="infiniscroll_timeout"></a>
<a id="istilldontcareaboutcookies_enabled"></a>
<a id="jsonl-url-parser-settings"></a>
<a id="mercury-settings"></a>
<a id="mercury_args"></a>
<a id="mercury_args_extra"></a>
<a id="mercury_binary"></a>
<a id="mercury_enabled"></a>
<a id="mercury_timeout"></a>
<a id="modal-closer-settings"></a>
<a id="modalcloser_enabled"></a>
<a id="modalcloser_poll_interval"></a>
<a id="modalcloser_timeout"></a>
<a id="netscape-url-parser-settings"></a>
<a id="papers-dl-settings"></a>
<a id="papersdl_args"></a>
<a id="papersdl_args_extra"></a>
<a id="papersdl_binary"></a>
<a id="papersdl_enabled"></a>
<a id="papersdl_timeout"></a>
<a id="parse_dom_outlinks_enabled"></a>
<a id="parse_dom_outlinks_timeout"></a>
<a id="parse_html_urls_enabled"></a>
<a id="parse_jsonl_urls_enabled"></a>
<a id="parse_netscape_urls_enabled"></a>
<a id="parse_rss_urls_enabled"></a>
<a id="parse_txt_urls_enabled"></a>
<a id="pdf-settings"></a>
<a id="pdf_enabled"></a>
<a id="pdf_resolution"></a>
<a id="pdf_timeout"></a>
<a id="readability-settings"></a>
<a id="readability_args"></a>
<a id="readability_args_extra"></a>
<a id="readability_binary"></a>
<a id="readability_enabled"></a>
<a id="readability_timeout"></a>
<a id="redirects-settings"></a>
<a id="redirects_enabled"></a>
<a id="redirects_timeout"></a>
<a id="responses-settings"></a>
<a id="responses_enabled"></a>
<a id="responses_timeout"></a>
<a id="ripgrep-search-settings"></a>
<a id="ripgrep_args"></a>
<a id="ripgrep_args_extra"></a>
<a id="ripgrep_binary"></a>
<a id="ripgrep_timeout"></a>
<a id="rss-url-parser-settings"></a>
<a id="screenshot-settings"></a>
<a id="screenshot_enabled"></a>
<a id="screenshot_resolution"></a>
<a id="screenshot_timeout"></a>
<a id="search_backend_sonic_bucket"></a>
<a id="search_backend_sonic_collection"></a>
<a id="search_backend_sonic_host_name"></a>
<a id="search_backend_sonic_password"></a>
<a id="search_backend_sonic_port"></a>
<a id="search_backend_sqlite_db"></a>
<a id="search_backend_sqlite_separate_database"></a>
<a id="search_backend_sqlite_tokenizers"></a>
<a id="seo-settings"></a>
<a id="seo_enabled"></a>
<a id="seo_timeout"></a>
<a id="singlefile-settings"></a>
<a id="singlefile_args"></a>
<a id="singlefile_args_extra"></a>
<a id="singlefile_binary"></a>
<a id="singlefile_check_ssl_validity"></a>
<a id="singlefile_chrome_args"></a>
<a id="singlefile_cookies_file"></a>
<a id="singlefile_enabled"></a>
<a id="singlefile_timeout"></a>
<a id="singlefile_user_agent"></a>
<a id="sonic-search-settings"></a>
<a id="sqlite-fts-search-settings"></a>
<a id="ssl-settings"></a>
<a id="ssl_enabled"></a>
<a id="ssl_timeout"></a>
<a id="static-file-settings"></a>
<a id="staticfile_enabled"></a>
<a id="staticfile_timeout"></a>
<a id="text-url-parser-settings"></a>
<a id="title-settings"></a>
<a id="title_enabled"></a>
<a id="title_timeout"></a>
<a id="trafilatura-settings"></a>
<a id="trafilatura_binary"></a>
<a id="trafilatura_enabled"></a>
<a id="trafilatura_output_csv"></a>
<a id="trafilatura_output_html"></a>
<a id="trafilatura_output_json"></a>
<a id="trafilatura_output_markdown"></a>
<a id="trafilatura_output_txt"></a>
<a id="trafilatura_output_xml"></a>
<a id="trafilatura_output_xmltei"></a>
<a id="trafilatura_timeout"></a>
<a id="twocaptcha_api_key"></a>
<a id="twocaptcha_auto_submit"></a>
<a id="twocaptcha_enabled"></a>
<a id="twocaptcha_retry_count"></a>
<a id="twocaptcha_retry_delay"></a>
<a id="twocaptcha_timeout"></a>
<a id="ublock-origin-settings"></a>
<a id="wget-settings"></a>
<a id="wget_args"></a>
<a id="wget_args_extra"></a>
<a id="wget_binary"></a>
<a id="wget_check_ssl_validity"></a>
<a id="wget_cookies_file"></a>
<a id="wget_enabled"></a>
<a id="wget_timeout"></a>
<a id="wget_user_agent"></a>
<a id="wget_warc_enabled"></a>
<a id="yt-dlp-settings"></a>
<a id="ytdlp_args"></a>
<a id="ytdlp_args_extra"></a>
<a id="ytdlp_binary"></a>
<a id="ytdlp_check_ssl_validity"></a>
<a id="ytdlp_cookies_file"></a>
<a id="ytdlp_enabled"></a>
<a id="ytdlp_max_size"></a>
<a id="ytdlp_timeout"></a>

> [!IMPORTANT]
> **Per-plugin configuration has moved to its own documentation site.**
> This `Configuration.md` doc covers only ArchiveBox's *core* settings. For everything that lives inside a plugin — extractor toggles, binary paths, timeouts, args, user agents, cookies, persona scoping, etc. — see:
>
> ## ➡️ **<https://archivebox.github.io/abx-plugins/>**

That site is regenerated from each plugin's `config.json` schema on every release, so it stays in sync with the code. Looking for [`WGET_ARGS`](https://archivebox.github.io/abx-plugins/#wget), [`CHROME_USER_DATA_DIR`](https://archivebox.github.io/abx-plugins/#chrome), [`SCREENSHOT_RESOLUTION`](https://archivebox.github.io/abx-plugins/#screenshot), [`YTDLP_EXTRA_ARGS`](https://archivebox.github.io/abx-plugins/#ytdlp), [`SINGLEFILE_*`](https://archivebox.github.io/abx-plugins/#singlefile), [`SONIC_HOST`](https://archivebox.github.io/abx-plugins/#search_backend_sonic), etc.? They all live there now.

### Shared core options that plugins fall back to

A handful of *core* options (documented above on this page) act as the **fallback default** for every plugin that has a matching per-extractor override. If you set the core option, every plugin honors it; if you also set the plugin-specific override, that wins for just that one plugin.

| Core option (this doc) | Plugin-level overrides (see [abx-plugins](https://archivebox.github.io/abx-plugins/)) |
|---|---|
| [`TIMEOUT`](#timeout) | [`WGET_TIMEOUT`](https://archivebox.github.io/abx-plugins/#wget), [`CHROME_TIMEOUT`](https://archivebox.github.io/abx-plugins/#chrome), [`YTDLP_TIMEOUT`](https://archivebox.github.io/abx-plugins/#ytdlp), [`SINGLEFILE_TIMEOUT`](https://archivebox.github.io/abx-plugins/#singlefile), [`TITLE_TIMEOUT`](https://archivebox.github.io/abx-plugins/#title), [`FAVICON_TIMEOUT`](https://archivebox.github.io/abx-plugins/#favicon), ... |
| [`CHECK_SSL_VALIDITY`](#check_ssl_validity) | [`WGET_CHECK_SSL_VALIDITY`](https://archivebox.github.io/abx-plugins/#wget), [`YTDLP_CHECK_SSL_VALIDITY`](https://archivebox.github.io/abx-plugins/#ytdlp), [`GALLERYDL_CHECK_SSL_VALIDITY`](https://archivebox.github.io/abx-plugins/#gallerydl), [`CHROME_CHECK_SSL_VALIDITY`](https://archivebox.github.io/abx-plugins/#chrome), ... |
| [`USER_AGENT`](#user_agent) | [`WGET_USER_AGENT`](https://archivebox.github.io/abx-plugins/#wget), [`CHROME_USER_AGENT`](https://archivebox.github.io/abx-plugins/#chrome), ... |
| [`COOKIES_FILE`](#cookies_file) | [`WGET_COOKIES_FILE`](https://archivebox.github.io/abx-plugins/#wget), [`YTDLP_COOKIES_FILE`](https://archivebox.github.io/abx-plugins/#ytdlp), [`GALLERYDL_COOKIES_FILE`](https://archivebox.github.io/abx-plugins/#gallerydl), ... |
| [`RESOLUTION`](#resolution) | [`SCREENSHOT_RESOLUTION`](https://archivebox.github.io/abx-plugins/#screenshot), [`PDF_RESOLUTION`](https://archivebox.github.io/abx-plugins/#pdf), [`CHROME_RESOLUTION`](https://archivebox.github.io/abx-plugins/#chrome) |

> [!TIP]
> The resolution order for any plugin-tunable option is always:
> **1.** `<PLUGIN>_<OPTION>` (explicit per-plugin override) →
> **2.** the matching shared core option above →
> **3.** the plugin's own hardcoded default.
>
> So setting `TIMEOUT=120` once at the top of your `ArchiveBox.conf` raises the timeout for *every* extractor at once; setting `CHROME_TIMEOUT=300` on top of that lifts it further for just Chrome.

### Listing & setting plugin options

All plugin options can be set via the same three mechanisms as core options — env var, `ArchiveBox.conf`, or `archivebox config --set` — and inspected with `archivebox config`:

```bash
archivebox config                                  # show every option (core + every installed plugin)
archivebox config --get SCREENSHOT_RESOLUTION      # read one value
archivebox config --set SCREENSHOT_RESOLUTION=1920,1080
archivebox config --search wget                    # search options by name/description
```

### Why is plugin config documented separately?

Plugin schemas evolve on their own release cadence — new extractors ship between ArchiveBox releases, options are added/renamed as hooks revise, and pinning their docs to the core release schedule produced unavoidable drift. The per-plugin doc is auto-generated from each plugin's `config.json` schema at build time, so it never lags behind the code.
