# Usage

▶️ _Make sure the dependencies are [fully installed](https://github.com/ArchiveBox/ArchiveBox/wiki/Install) before running any ArchiveBox commands._

**ArchiveBox API Reference:**

<img src="https://imgur.zervice.io/aQZZcku.png" width="20%" align="right"/>

- [CLI Usage](#CLI-Usage): Docs and examples for the ArchiveBox command line interface.
- [Admin UI Usage](#UI-Usage): Docs and screenshots for the outputted HTML archive interface.
- [Browser Extension Usage](#Browser-Extension-Usage): Docs and screenshots for the outputted HTML archive interface.
- [Disk Layout](#Disk-Layout): Description of the archive folder structure and contents.

**Related:**

- [[Docker]]: Learn about ArchiveBox usage with Docker and Docker Compose
- [[Configuration]]: Learn about the various archive method options
- [[Scheduled Archiving]]: Learn how to set up automatic daily archiving
- [[Publishing Your Archive]]: Learn how to host your archive for others to access
- [[Troubleshooting]]: Resources if you encounter any problems

## CLI Usage

<img src="https://imgur.zervice.io/biVfFYr.png" width="30%" align="right"/>

All three of these ways of running ArchiveBox are equivalent and interchangeable:

- `archivebox [subcommand] [...args]`  
  *Using the Python package via the current `uv` instructions in [[Install]]*
- `docker run ... archivebox/archivebox [subcommand] [...args]`  
  *Using the official Docker image*
- `docker compose run --rm archivebox [subcommand] [...args]`
  *Using the official Docker image w/ Docker Compose*

You can share a single archivebox data directory between Docker and non-Docker instances as well, allowing you to run the server in a container but still execute CLI commands on the host for example.

For more examples see [README: Usage](https://github.com/ArchiveBox/ArchiveBox#%EF%B8%8F-cli-usage) and [[Docker]] pages.

- [Run ArchiveBox with configuration options](#Run-ArchiveBox-with-configuration-options)
- [Import a single URL](#Import-a-single-URL)
- [Import a list of URLs from a text file](#Import-a-list-of-URLs-from-a-text-file)
- [Import list of links from browser history](#Import-list-of-links-from-browser-history)

---

### Run ArchiveBox with configuration options

You can set environment variables in your shell profile, a config file, or by using the `env` command.

```bash
# set config via the CLI
archivebox config --set TIMEOUT=120

# OR edit ArchiveBox.conf and add this under its existing [ARCHIVING_CONFIG] section:
TIMEOUT=120

# OR use environment variables
env TIMEOUT=120 archivebox add 'https://example.com'
```

See [[Configuration]] page for core ArchiveBox config options and the [abx-plugins config reference](https://archivebox.github.io/abx-plugins/) for per-plugin options (e.g. `YTDLP_MAX_SIZE`, `CHROME_USER_DATA_DIR`, `WGET_ARGS`, etc.).
If you're using Docker, also make sure to read the Configuration section on the [[Docker]] page.

> [!TIP]  
> You can run ArchiveBox commands from anywhere (without having to `cd` into a data directory first):  
> `/usr/bin/env --chdir=/path/to/archivebox/data archivebox update`

---

### Import a single URL

```bash
archivebox add 'https://example.com'
# OR
echo 'https://example.com' | archivebox add
```

You can also add `--depth=1` to any of these commands if you want to recursively archive the URLs and all URLs one hop away. (e.g. all the outlinks on a page + the page).

### Import a list of URLs from a text file

```bash
cat urls_to_archive.txt | archivebox add
# OR
archivebox add < urls_to_archive.txt
# OR
curl 'https://example.com/some/rss/feed.xml' | archivebox add
# OR
archivebox add --depth=1 'https://example.com/some/rss/feed.xml'
```

You can also pipe in RSS, XML, Netscape, or any of the other [supported import formats](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive) via stdin.

```bash
archivebox add < ~/Downloads/browser_bookmarks_export.html
# OR
archivebox add < ~/Downloads/pinboard_bookmarks.json
# OR
archivebox add < ~/Downloads/any_text_containing_urls.txt
```

---

### Import list of links from browser history

Look in the `bin/` folder of this repo to find a script to parse your browser's SQLite history database for URLs.
Specify the type of the browser as the first argument, and optionally the path to the SQLite history file as the second argument.

```bash
bash ./bin/export_browser_history.sh --chrome
archivebox add < chrome_history.json
# or
bash ./bin/export_browser_history.sh --firefox
archivebox add < firefox_history.json
# or
bash ./bin/export_browser_history.sh --safari
archivebox add < safari_history.json
```

<br/>

---

<br/>

### Import browser cookies into a persona

To archive logged-in sites, you can import cookies from your browser into a persona. This generates a `cookies.txt` file in the persona directory (used by wget/curl/yt-dlp, etc.) and, for Chromium-based browsers, also copies the profile into the persona so Chrome-based extractors can reuse it.

```bash
archivebox persona create --import=chrome personal
# supported: chrome/chromium/brave/edge (Chromium-based only)
# use --profile to target a specific profile (e.g. Default, Profile 1)
# re-running import merges/dedupes cookies.txt (by domain/path/name) but replaces chrome_user_data
```

If cookie extraction fails, you can still export a Netscape-format `cookies.txt` using a browser extension and place it at `data/personas/<NAME>/cookies.txt`.

<br/>

---

<br/>

## UI Usage

```bash
# configure which areas you want to require login to use vs make publicly available
archivebox config --set PUBLIC_INDEX=False
archivebox config --set PUBLIC_ADD_VIEW=False
archivebox config --set PERMISSIONS=private        # default visibility of newly created snapshots (was: PUBLIC_SNAPSHOTS=False)

archivebox server 0.0.0.0:8000     # start the archivebox web server
```

Open <http://admin.archivebox.localhost:8000/admin/> in a browser to create the first admin and finish web setup. To create additional accounts from the CLI, use `archivebox manage createsuperuser`.

*See the [Configuration Wiki](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#permissions) and [Security Wiki](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#archiving-private-content) for more info...*

Or if you prefer to generate a [static HTML index](https://github.com/ArchiveBox/ArchiveBox#static-archive-exporting) instead of using the built-in web server, you can run `archivebox list --html --with-headers > ./index.html` and then open `./index.html` in a browser.  You should see something [like this](https://demo.archivebox.io).

You can sort by column, search using the box in the upper right, and see the total number of links at the bottom.

Click the Favicon under the "Files" column to go to the details page for each link.

<div align="center">
<img src="https://imgur.zervice.io/52RjhUM.png" width="45%" align="top"/>
<img src="https://imgur.zervice.io/Gg9sTyq.png" width="45%" align="top"/>
</div>

### Explanation of buttons in the web UI - admin snapshots list

<img src="https://imgur.zervice.io/4Sa76Ek.png" alt="Screenshot of buttons at top of Snapshot admin page"/>

A logged-in admin user may select ☑️ one or more snapshots from the list and perform Snapshot actions:

- <kbd>Search</kbd> Search text in the Snapshot title, URL, tags, or archived content. [Sonic](https://github.com/valeriansaliou/sonic) is the default indexed search backend, with ripgrep enabled as the filesystem fallback and regex-search option. https://github.com/ArchiveBox/ArchiveBox/issues/956
- <kbd>Tags</kbd> Start typing in the field to select some tags, then click `+` to add them or `-` remove them from the checked snapshots (`Tags` can be created/edited from the `/admin/core/tag/` page)
- <kbd>Title</kbd> Pull the latest title and favicon without doing a full snapshot. (helpful to quickly ping any URLs that are stuck showing up as `Pending...` or are missing a title)
- <kbd>Pull</kbd> Finish downloading the Snapshot, pulls any missing/failed outputs/extractors methods (pdf, wget... etc). Resumes running the same archiving steps as when you add new URL. Useful to finish pulling when previous import was paused or interrupted by a reboot or something.  https://github.com/ArchiveBox/ArchiveBox#output-formats
- <kbd>Re-Snapshot</kbd> Re-archive the original URL from scratch as a new separate snapshot. Differs from pulling in that it doesn't resume/update existing snapshot, it creates a new separate entry and re-snapshots the URL at the current point in time. (useful for saving multiple Snapshots of a single URL over time) https://github.com/ArchiveBox/ArchiveBox#saving-multiple-snapshots-of-a-single-url
- <kbd>Reset</kbd> Keep the Snapshot entry, but delete all its archive results and redownload them from scratch immediately. Useful for re-trying a bad Snapshot and overwriting its previous results, e.g. if it initially archived a temporary error page or hit a transient rate-limit/CAPTCHA/login page.
- <kbd>Delete</kbd> Delete a snapshot and all its archive results entirely. This action cannot be undone. (Note: to thoroughly remove every trace of a URL ever being added, you should also manually scrub log output found in `sources/` and `logs/`)

<br/>

---

<br/>

## Browser Extension Usage

Set up the official [ArchiveBox Browser Extension](https://github.com/ArchiveBox/archivebox-browser-extension) to submit URLs directly from your browser to ArchiveBox.

1. Install the extension in your browser:
   - [Google Chrome / Edge / All Chromium-based browsers...](https://chrome.google.com/webstore/detail/habonpimjphpdnmcfkaockjnffodikoj)
   - [Firefox](https://addons.mozilla.org/en-US/firefox/addon/archivebox-exporter/)

2. Log into your ArchiveBox server's admin UI in the same browser where you installed the extension, e.g.  
   [`http://localhost:8000/admin/`](http://localhost:8000/admin/) or `https://demo.archivebox.io/admin/`  
   The extension will re-use your admin UI login session to submit URLs to your server, so *make sure to log in!*  
   . . .   
   *Alternatively:* You can configure Archivebox to [allow submitting URLs without requiring log-in](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#public_index--public_snapshots--public_add_view)  
   `archivebox config --set PUBLIC_ADD_VIEW=True`

3. Click the ArchiveBox extension in your browser and set `Config > ArchiveBox Base URL` to your server's URL, e.g.  
   `http://localhost:8000` or `https://demo.archivebox.io`

4. ✅ Done! Test it out: `Right-click on any page > ArchiveBox Exporter > Archive Current Page`  
   *Then check your ArchiveBox instance to confirm the URL was added.*

<img width="400" align="right" alt="browser extension config screen" src="https://user-images.githubusercontent.com/511499/215702958-4683af8f-7f1e-4b0e-a313-2466b9cf0276.png"/>
<img width="350" align="top" alt="chrome web store screenshot" src="https://user-images.githubusercontent.com/511499/215699375-5c98c9bb-56fd-4a46-a990-e5745d46019c.png"/><br/><img width="400" alt="image" src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/8bdd99a8-656b-4839-937d-80670ec4d8a6">

#### More Info

- https://github.com/ArchiveBox/archivebox-browser-extension
- https://github.com/ArchiveBox/archivebox-browser-extension#setup
- https://github.com/ArchiveBox/archivebox-browser-extension#features
- https://github.com/ArchiveBox/archivebox-browser-extension#alternative-extensions-for-archiving
- https://github.com/ArchiveBox/ArchiveBox/issues/577

<br/>

---

<br/>

## Disk Layout

The `OUTPUT_DIR` folder (usually whatever folder you run the `archivebox` command in), contains the UI HTML and archived data with the structure outlined below.

Simply back up the entire `data/` folder to back up your archive, e.g. `zip -r data.backup.zip data`.

```yaml
 - data/
   - index.sqlite3        # Main index of all archived URLs
   - ArchiveBox.conf      # Main config file in ini format

   - archive/
      - 155243135 -> users/admin/snapshots/20210406/example.com/SNAPSHOT_UUID/
      - users/
         - admin/
            - snapshots/
               - 20210406/
                  - example.com/
                     - SNAPSHOT_UUID/
                        - index.jsonl
                        - index.html

                        # Archive method outputs:
                        - wget/warc/
                        - ytdlp/media/
                        - git/
                        ...

   - sources/             # Each imported URL list is saved as a copy here
      - getpocket.com-1552432264.txt
      - stdin-1552291774.txt
      ...
```

For more info about ArchiveBox's database/filesystem layout and troubleshooting steps:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#output-folder
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#modify-the-archivebox-sqlite3-db-directly
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#database-troubleshooting


### Large Archives

I've found it takes about an hour to download 1000 articles, and they'll take up roughly 1GB.  
Those numbers are from running it single-threaded on my i5 machine with 50mbps down. YMMV.

Storage requirements go up immensely if you're using [`MEDIA_ENABLED=True`](https://archivebox.github.io/abx-plugins/#media) (or its [`FETCH_MEDIA`](https://archivebox.github.io/abx-plugins/#ytdlp) / `YTDLP_ENABLED` aliases) and are archiving many pages with audio & video.

ArchiveBox's unified crawl runner handles bounded concurrency without starting competing writers:
```bash
env CRAWL_MAX_CONCURRENT_SNAPSHOTS=4 archivebox add < urls_to_archive.txt
```
Higher concurrency is not always faster on slow disks or network filesystems, so increase it gradually.

Users have reported running it with 50k+ bookmarks with success (though it will take more RAM while running).

If you already imported a huge list of bookmarks and want to import only new
bookmarks, you can use the `ONLY_NEW` environment variable. This is useful if
you want to import a bookmark dump periodically and want to skip broken links
which are already in the index.

For more info about troubleshooting filesystem permissions, performance, or issues when running on a NAS:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#output-folder
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#database-troubleshooting

<br/>

---

<br/>

## SQL Shell Usage

Explore the SQLite3 DB a bit to see what's available using the SQLite3 shell:
```bash
cd ~/archivebox/data
sqlite3 index.sqlite3

# example usage:
SELECT * FROM core_snapshot;
UPDATE auth_user SET email = 'someNewEmail@example.com' WHERE username = 'someUsernameHere';
...
```

More info:
- https://github.com/ArchiveBox/ArchiveBox#-sqlpythonfilesystem-usage
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#modify-the-archivebox-sqlite3-db-directly
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#database-troubleshooting
- https://stackoverflow.com/questions/1074212/how-can-i-see-the-raw-sql-queries-django-is-running
- https://adamobeng.com/wddbfs-mount-a-sqlite-database-as-a-filesystem/

<br/>

---

<br/>

## Python Shell Usage

Explore the Python API a bit to see what's available using the archivebox shell:

**Python API Documentation:** https://docs.archivebox.io/dev/apidocs/index.html

```bash
$ archivebox shell
[i] ArchiveBox shell
>>> from archivebox.core.models import Snapshot
>>> from archivebox.cli.archivebox_add import add

# count completed snapshots
>>> print(Snapshot.objects.filter(status=Snapshot.StatusChoices.SEALED).count())
24

# inspect or add URLs through current APIs
>>> Snapshot.objects.filter(url="https://example.com").first()
<Snapshot: https://example.com>
>>> crawl, snapshots = add(urls=["https://example.com/new"], index_only=True)

# show raw SQL queries run
>>> from django.db import connection
>>> print(connection.queries)
```

For more info and example usage:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#example-adding-a-new-user-with-a-hashed-password
- https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/cli/
- https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/config/common.py
- https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/core/models.py
- https://stackoverflow.com/questions/1074212/how-can-i-see-the-raw-sql-queries-django-is-running

<br/>

---

<br/>

## Python API Usage

You can interact with ArchiveBox as a Python library from external scripts or programs.

This API is a *local* API, designed to be used on the same machine as the ArchiveBox collection.

For example, you could create a script `add_archivebox_url.py` like so:
```python
import os
from pathlib import Path

DATA_DIR = Path("~/archivebox/data").expanduser()
os.chdir(DATA_DIR)

# you must import and setup django first to establish a DB connection
from archivebox.config.django import setup_django
setup_django(check_db=True)

# then import the specific API you need
from archivebox.cli.archivebox_add import add

crawl, snapshots = add(urls=["https://example.com"], index_only=True)
print(crawl.id, list(snapshots.values_list("id", flat=True)))
```

For more information see:
- [ArchiveBox Python API Reference (ReadTheDocs)](https://docs.archivebox.io/dev/apidocs/index.html)
- [ArchiveBox Developer Documentation](https://github.com/ArchiveBox/ArchiveBox#archivebox-development)
- [ArchiveBox Python source code](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/)
