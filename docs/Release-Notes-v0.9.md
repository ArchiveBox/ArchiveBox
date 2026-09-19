# ArchiveBox v0.9.x: Safer, Faster, and Much More Powerful Web Archiving

ArchiveBox v0.9 is our biggest release since the 0.7.x series. It makes everyday archiving easier to set up, easier to operate, more reliable at scale, and substantially safer when browsing saved pages.

> [!IMPORTANT]
> Back up your ArchiveBox data directory before upgrading. v0.9 migrates both the database and on-disk archive layout. Test the upgrade on a copy first, especially for large or customized installations.

## ✨ What's New in v0.9.x

- 🧙 **A much easier first-run experience.** A new browser-based setup wizard guides you through creating an admin account, choosing collection settings, and getting your first archive running without hand-editing configuration files.

- 📱 **A faster, richer interface on every device.** Snapshot cards, previews, action menus, archive-result views, and nearly every other page have been redesigned to work comfortably across phones, tablets, and desktops. Almost all UI pages are served in ~100ms or less—even with 1 million Snapshots in the database.

- 📡 **Live progress you can actually follow.** Crawl, Snapshot, process, and extractor status now update while work is running, with clearer visibility into what succeeded, what failed, and what is still queued.

- ⏯️ **Durable crawls that survive interruptions.** Crawls can be paused, resumed, aborted, retried, and recovered after restarts instead of existing only as a single fragile command. ArchiveBox also prevents multiple competing runners from processing the same collection.

- 🗓️ **Scheduling is built into ArchiveBox.** Recurring imports and crawls are stored in the database and run by the server, removing the need to maintain a separate cron process or Docker sidecar.

- 👤 **Personas preserve real browser identities.** Import a Chrome profile—including cookies and authenticated sessions—into a named Persona, then choose that Persona when archiving sites that require a login or personalized browser state.

  ```bash
  archivebox persona create --import=chrome personal
  archivebox add --persona=personal https://example.com
  ```

- 🎯 **More consistent, reliable captures.** Extractors now share clearer configuration and output rules, dependencies can be installed automatically, and each extractor writes to a predictable namespaced folder. This makes failures easier to understand and custom capture workflows easier to build.

- 🌐 **Better browser isolation between crawls.** Chrome processes, profiles, tabs, and sessions are tracked per crawl so simultaneous jobs interfere with each other less and browser resources are cleaned up more reliably.

- 🛡️ **Safer replay of archived pages.** ArchiveBox now separates the admin, API, web UI, and archived-page origins. Full interactive replay can use isolated `*.localhost` subdomains, while normal hosts use a safer no-JavaScript replay mode to reduce the risk from untrusted archived content.

- 🔐 **More precise privacy and stronger request security.** Individual Snapshots can be public, unlisted, or private, and authentication, cookie, CSRF, redirect, and webhook handling have been hardened across the web and API surfaces.

- 🔎 **Much better search choices.** Collections can use SQLite full-text search, Sonic, or ripgrep depending on size and deployment needs, with improved indexing and search behavior across titles, URLs, tags, and captured text.

- 🐘 **Optional PostgreSQL support.** SQLite remains the simple default, while larger or more concurrent deployments can now use PostgreSQL. SQLite locking and Docker bind-mount behavior have also been improved.

- 🔌 **A substantially expanded automation surface.** The Django Ninja REST API now exposes more collection, crawl, Snapshot, result, tag, user, token, and operational workflows. API tokens, outbound webhooks, and browser-extension uploads make ArchiveBox easier to connect to other tools.

- 🤖 **Optional AI agents and Claude-powered archiving.** Disabled by default, the built-in `archivebox mcp` server lets a dedicated AI agent perform crawls, search and manage your archive, prune duplicate results, and more. New optional plugins add [Claude-powered browser interaction](https://plugins.archivebox.io/#claudechrome), [custom content extraction](https://plugins.archivebox.io/#claudecodeextract), and [duplicate-result cleanup](https://plugins.archivebox.io/#claudecodecleanup).

- 📦 **Simpler dependency and installation management.** `archivebox install` can discover and install required browser and command-line dependencies, and `uv tool install archivebox` provides a cleaner native installation path with isolated Python dependencies.

- 🐳 **More dependable deployments and packages.** Docker startup, health checks, configuration, permissions, Chromium behavior, and multi-container operation have been tightened up. Homebrew and Debian packaging are available again as thin wrappers around the same supported ArchiveBox runtime.

- 🗂️ **A scalable, inspectable archive layout.** New archives use human-readable date/domain paths with a stable Snapshot UUID and JSONL metadata. Static exports, large-collection traversal, and moving or inspecting archives outside ArchiveBox are more reliable.

- 🚦 **Better controls for large and unattended crawls.** New crawl limits and retention settings can bound runtime, depth, size, and stored output, while improved process and machine visibility makes it easier to diagnose stuck or resource-heavy jobs.

## ⬆️ Upgrading

Upgrade from a backup and allow time for both database and filesystem migrations.

### Docker Compose

```bash
cd ~/archivebox
docker compose down
cp -a data "data.backup-$(date +%Y%m%d)"
docker compose pull
docker compose run --rm archivebox init
docker compose run --rm archivebox update --migrate-only
docker compose up -d
docker compose exec archivebox archivebox status
```

### Native / uv

```bash
uv tool install --python 3.13 --upgrade archivebox
cd ~/archivebox/data
archivebox init
archivebox install
archivebox update --migrate-only
archivebox status
```

<details>
<summary><strong>🏗️ Internal architecture and package changes</strong></summary>

ArchiveBox's capture stack is now split into smaller reusable projects:

- [abxbus](https://github.com/ArchiveBox/abxbus) provides typed events and process coordination.
- [abxpkg](https://github.com/ArchiveBox/abxpkg) discovers, installs, and runs external binary dependencies.
- [abx-plugins](https://github.com/ArchiveBox/abx-plugins) contains extractor and plugin definitions.
- [abx-dl](https://github.com/ArchiveBox/abx-dl) provides the standalone downloader and extraction pipeline.
- [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox) adds the database, web UI, API, scheduling, access control, and collection management.

The application now records crawls, processes, machines, workers, configurations, binaries, and archive results as durable database objects. This supports live status, recovery, scheduling, auditing, and clearer failure reporting without making those implementation details part of the normal archiving workflow.

Release builds are versioned through this dependency chain, so final package and container releases must use mutually compatible versions.

</details>

<details>
<summary><strong>🔄 Migration and filesystem details</strong></summary>

The v0.9 migration preserves existing Snapshots, tags, users, ArchiveResults, and archive files while upgrading the database and converting legacy archive directories to the new layout:

```text
data/archive/users/<username>/snapshots/<date>/<domain>/<uuid>/index.jsonl
```

Run `archivebox init` first to apply database migrations, then `archivebox update --migrate-only` to migrate archive directories. The migration is designed to be resumable and idempotent, but large collections can take significant time and should always be upgraded from a tested backup.

The 0.7.x stable line and the 0.9 development line diverged historically, so these notes summarize the user-visible change between the release families rather than a single linear commit range.

</details>

<details>
<summary><strong>⚠️ Compatibility notes</strong></summary>

- Python 3.13 or newer is required for native installs.
- Custom plugins and extractors must use the current executable plugin contract and namespaced output directories.
- Access control is now evaluated per Snapshot; review public, unlisted, and private defaults after migration.
- Only one active runner should operate on a given ArchiveBox data directory.
- Native installations should run `archivebox install` after upgrading to resolve external dependencies.
- PostgreSQL is optional, but ArchiveBox does not provide an automatic SQLite-to-PostgreSQL data conversion.
- Test customized Docker Compose files, reverse proxies, replay hostnames, and webhook integrations against a copied collection before production rollout.

</details>

<details>
<summary><strong>🙌 Contributors and reporters</strong></summary>

Thank you to everyone who contributed code, documentation, testing, bug reports, and responsible security reports during the long road from 0.7.x to 0.9.x.

**Code and documentation contributors**
Sorted approximately by the size and quantity of accepted contributions:

@Brandl, @jimwins, @benmuth, @FellowTraveler, @pcrockett, @tqobqbq, @pellaeon, @sclu1034, @vladimirdulov, @andrew-d, @n-hebert, @gnattu, @danielalanbates, @boehs, @pyrox0, @ckiee, @neel-suthar, @dicnunz, @zkksdk, @1over137, @agowa, @benharri, @ckcr4lyf, @jasongodev, @naoph, @rdela, @slmingol, @ssoel, @TrisSherliker, @NelsonMinar, and @mpgirro.

**Issue reporters whose reports led to fixes**
This list excludes people already credited above for accepted code or documentation:

@amy-r-oss, @saiarcot895, @cyberproaustin, @BenCzaczkes, @larsony99, @tztzz, @JitteryDoodle, @Finkregh, @philippemilink, @sbutcher, @melyux, @m0nhawk, @danst0, @KagurazakaShirosatosu, @s7x, @mawmawmawm, and @cdzombak.

**Security advisory reporters explicitly promised release-note credit**
This is intentionally limited to advisory threads where the maintainer explicitly said the reporter would be credited:

@DavidCarliez, @FUNFACTOR1, @g4nkd, @geo-chen, @iaohkut-from-NightWolf-Team, and @Vasco0x4.

</details>

<details>
<summary><strong>🔗 Related projects, documentation, and full changelog</strong></summary>

- [ArchiveBox documentation](https://docs.archivebox.io/)
- [ArchiveBox browser extension](https://github.com/ArchiveBox/archivebox-browser-extension)
- [ArchiveBox REST API documentation](https://docs.archivebox.io/dev/#rest-api)
- [ArchiveBox releases](https://github.com/ArchiveBox/ArchiveBox/releases)
- [Full source comparison from v0.7.4 to the current v0.9 release candidate](https://github.com/ArchiveBox/ArchiveBox/compare/v0.7.4...v0.9.35rc410)

Before publishing, replace the release-candidate version in the heading and comparison link with the final v0.9 tag.

</details>
