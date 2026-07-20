# Changelog

▶️ *If you're having an issue with a breaking change, or migrating your data between versions, open an [issue](https://github.com/ArchiveBox/ArchiveBox/issues) to get help.*

**`ArchiveBox` was previously named `Pocket Archive Stream` and then `Bookmark Archiver`.**

<br/>

<div align="center">

**`THIS PAGE HAS BEEN MOVED:` See the [releases](https://github.com/ArchiveBox/ArchiveBox/releases) page for versioned source downloads and full changelog.**


🍰 Many thanks to our 100+ contributors and everyone in the web archiving community! 🏛

</div>

<details>
<summary>Expand old release notes...</summary>

---

 - v0.4.9 released
   - `pip install archivebox` https://pypi.org/project/archivebox/
   - `docker run archivebox/archivebox` https://hub.docker.com/r/archivebox/archivebox
   - https://archivebox.readthedocs.io/en/latest/
   - https://github.com/ArchiveBox/ArchiveBox/releases
 - easy migration from previous versions
   ```bash
   export PLUGINS=parse_txt_urls
   archive_dir="$(mktemp -d)"
   cd "$archive_dir"
   archivebox init
   archivebox add --plugins=parse_txt_urls 'https://example.com'
   ```
 - full transition to Django Sqlite DB with migrations (making upgrades between versions much safer now)
 - maintains an intuitive and helpful CLI that's backwards-compatible with all previous archivebox data versions
 - uses argparse instead of hand-written CLI system: see `archivebox/cli/archivebox.py`
 - new subcommands-based CLI for `archivebox` (see below)
 - new Web UI with pagination, better search, filtering, permissions, and more
 - 30+ assorted bugfixes, new features, and tickets closed
 - for more info, see: https://github.com/ArchiveBox/ArchiveBox/releases/tag/v0.4.9

---

 - v0.2.4 released
 - better archive corruption guards (check structure invariants on every parse & save)
 - remove title prefetching in favor of new FETCH_TITLE archive method
 - slightly improved CLI output for parsing and remote url downloading
 - re-save index after archiving completes to update titles and urls
 - remove redundant derivable data from link json schema
 - markdown link parsing support
 - faster link parsing and better symbol handling using a new compiled URL_REGEX

---

 - v0.2.3 released
 - fixed issues with parsing titles including trailing tags
 - fixed issues with titles defaulting to URLs instead of attempting to fetch
 - fixed issue where bookmark timestamps from RSS would be ignored and current ts used instead
 - fixed issue where ONLY_NEW would overwrite existing links in archive with only new ones
 - fixed lots of issues with URL parsing by using `urllib.parse` instead of hand-written lambdas
 - ignore robots.txt when using wget (ssshhh don't tell anyone 😁)
 - fix RSS parser bailing out when there's whitespace around XML tags
 - fix issue with browser history export trying to run ls on wrong directory

---

 - v0.2.2 released
 - Shaarli RSS export support
 - Fix issues with plain text link parsing including quotes, whitespace, and closing tags in URLs
 - add USER_AGENT to archive.org submissions so they can track archivebox usage
 - remove all icons similar to archive.org branding from archive UI
 - hide some of the noisier youtubedl and wget errors
 - set permissions on youtubedl media folder
 - fix chrome data dir incorrect path and quoting
 - better chrome binary finding
 - show which parser is used when importing links, show progress when fetching titles

---

 - v0.2.1 released with new logo
 - ability to import plain lists of links and almost all other raw filetypes
 - WARC saving support via wget
 - Git repository downloading with git clone
 - Media downloading with youtube-dl (video, audio, subtitles, description, playlist, etc)

---
 - v0.2.0 released with new name
 - [renamed](https://github.com/ArchiveBox/ArchiveBox/issues/108) from **Bookmark Archiver** -> **ArchiveBox**

---
 - v0.1.0 released
 - support for browser history exporting added with `./bin/archivebox-export-browser-history`
 - support for chrome `--dump-dom` to output full page HTML after JS executes

---
 - v0.0.3 released
 - support for chrome `--user-data-dir` to archive sites that need logins
 - fancy individual html & json indexes for each link
 - smartly append new links to existing index instead of overwriting 

---
 - v0.0.2 released
 - proper HTML templating instead of format strings (thanks to https://github.com/bardisty!)
 - refactored into separate files, wip audio & video archiving

---
 - v0.0.1 released
 - Index links now work without nginx url rewrites, archive can now be hosted on github pages
 - added setup.sh script & docstrings & help commands
 - made Chromium the default instead of Google Chrome (yay free software)
 - added [env-variable](https://github.com/ArchiveBox/ArchiveBox/pull/25) configuration (thanks to https://github.com/hannah98!)
 - renamed from **Pocket Archive Stream** -> **Bookmark Archiver**
 - added [Netscape-format](https://github.com/ArchiveBox/ArchiveBox/pull/20) export support (thanks to https://github.com/ilvar!)
 - added [Pinboard-format](https://github.com/ArchiveBox/ArchiveBox/pull/7) export support (thanks to https://github.com/sconeyard!)
 - front-page of HN, oops! apparently I have users to support now :grin:?
 - added Pocket-format export support

---
 - v0.0.0 released: created Pocket Archive Stream 2017/05/05

</details>
