# ArchiveBox v0.9 is now released. 🎉

It's been a long time since our last major release back in 2024!
Thanks for hanging in there, but I promise this release was worth the wait!

**[↗️ ArchiveBox 0.9](https://archivebox.io)** brings an entirely new archiving engine, massive performance & stability gains, UI improvements, all-new mobile & desktop apps, and 50+ new plugins.

> ## [📖 Read the full Announcement Post ↗️](https://docs.sweeting.me/s/archivebox-v0.9-announcement)

![iPhone and Android, using the device-framed screenshots from the official app sites.](https://docs.monadical.com/uploads/8c5b7349-f5c2-4db8-94ec-1addb8591d24.png)

<img src="https://app.archivebox.io/screenshots/images/macos/snapshots.png?v=1b23a271df90" alt="ArchiveBox for macOS" width="640">

## ✨ The big changes

- 📱 **NEW Native Mobile & Desktop Apps:** [iPhone](https://app.archivebox.io/) / [iPad](https://app.archivebox.io/) / [Android](https://android.archivebox.io/) &nbsp; | &nbsp; [macOS](https://app.archivebox.io/) / [Windows](https://electron.archivebox.io/) / [Linux](https://electron.archivebox.io/)
- 🗂️ **Redesigned output viewers:** beautiful new viewers for article text, extracted video/audio, metadata + more
- 🧭 **Vastly improved browser extension:** import bookmarks/history, uploads local screenshot & MHTML
- 🐘 **PostgreSQL support:** SQLite remains the default, but we caved to demand and finally added PostgreSQL
- 🗓️ **Scheduled crawls in the UI:** schedule recurring import jobs directly from the UI, all in one Docker container
- 👤 **Personas:** archive sites logged-in using cookies & settings synced from extension, CDP, or local browsers
- 🤖 **AI Tools:** new MCP server, SKILL.md, and built-in agent (opencode) that can handle custom archiving tasks
- 🔏 **Bulletproof chain-of-custody:** new merkle hashes, TLSNotary attestation, and OpenTimestamps integration
- ⬇️ **A new standalone oneshot CLI:** `abx-dl` uses the same plugins without needing a full ArchiveBox server

## 🗂️ More useful saved pages

- **Responsive layouts** across phone, tablet, and desktop.
- **Expandable output stacks** group related capture formats together.
- **Article and document readers** for extracted text, including PDF extraction outputs.
- **Media galleries and players** for images, audio, video, and captured browser responses.
- **Repository previews** with a file browser and rendered README.
- **Readable metadata views:** redirects, headers, DNS, certificates, accessibility trees, browser activity, and console logs.
- **View raw, download one output, browse all files, or download a snapshot ZIP.**

![New metadata cards and expandable output stacks](https://archivebox.io/screenshots/snapshot-view-sslcerts-tablet.png)

## 🔏 Keep evidence you can check later

| Tool | What it adds |
| --- | --- |
| **Hashes** | Full sha256 merkle tree hashing all the archived snapshot output when it's sealed. |
| **TLSNotary** | An optional verifier server witnesses a TLS response without needing the private page body or cookies revealed to it. Allows for anonymous, secure 3rd-party attestation. |
| **OpenTimestamps** | Store a merkle hash+salt of all the archived content at a point in time. |

## ⬆️ Upgrading from 0.7.x

**Make a full offsite backup of your ArchiveBox data directory before upgrading, and be aware 0.9 will move some data/ dir files to new filesystem locations.** Filesystem migration is done lazily, and can be interrupted / resumed at will.

1. **Stop the old server.** `docker compose down`
2. **Back up the entire collection:** database, configuration, archive files, and browser Personas. A database-only backup isn't enough.
3. **Install 0.9.x following the instructions for your platform.** See https://archivebox.io
4. **Run `archivebox init` to upgrade the database.** Migrations can take minutes to hours depending on db size.
5. Run `archivebox update --migrate-only` to start migrating filesystem data to the new locations (if this is skipped, it will happen lazily on first access and may slow down the UI)
6. **Keep the backup until you've verified the final setup looks good!**

For Docker Compose, **update your [`docker-compose.yml`](https://docker-compose.archivebox.io) first**, then:

```bash
docker compose run archivebox init
docker compose run archivebox update --migrate-only
docker compose down --remove-orphans
docker compose up -d
```

[Upgrade guide](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading) · [Merging collections](https://github.com/ArchiveBox/ArchiveBox/blob/dev/docs/Merging-Collections.md) · [🐛 Report an issue](https://github.com/ArchiveBox/ArchiveBox/issues/new/choose)

**Full Changelog:** https://github.com/ArchiveBox/ArchiveBox/compare/v0.7.4...main
