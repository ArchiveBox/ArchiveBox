<div align="center">
<em><img src="https://i.imgur.com/5B48E3N.png" height="90px"></em>
<h1>ArchiveBox<br/><sub>Open-source self-hosted web archiving.</sub></h1>

▶️ <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart">Quickstart</a> |
<a href="https://archivebox.zervice.io/">Demo</a> |
<a href="https://github.com/ArchiveBox/ArchiveBox">Github</a> |
<a href="https://github.com/ArchiveBox/ArchiveBox/wiki">Documentation</a> |
<a href="#background--motivation">Info & Motivation</a> |
<a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community">Community</a> |
<a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap">Roadmap</a>

<pre>
"Your own personal internet archive" (网站存档 / 爬虫)
</pre>

<!--<a href="http://webchat.freenode.net?channels=ArchiveBox&uio=d4"><img src="https://img.shields.io/badge/Community_chat-IRC-%2328A745.svg"/></a>-->

<a href="https://github.com/ArchiveBox/ArchiveBox/blob/master/LICENSE"><img src="https://img.shields.io/badge/Open_source-MIT-green.svg?logo=git&logoColor=green"/></a>
<a href="https://github.com/ArchiveBox/ArchiveBox"><img src="https://img.shields.io/github/stars/ArchiveBox/ArchiveBox.svg?logo=github&label=Stars&logoColor=blue"/></a>
<a href="https://test.pypi.org/project/archivebox/"><img src="https://img.shields.io/badge/Python-%3E%3D3.7-yellow.svg?logo=python&logoColor=yellow"/></a>
<a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Install#dependencies"><img src="https://img.shields.io/badge/Chromium-%3E%3D59-orange.svg?logo=Google+Chrome&logoColor=orange"/></a>
<a href="https://hub.docker.com/r/archivebox/archivebox"><img src="https://img.shields.io/badge/Docker-all%20platforms-lightblue.svg?logo=docker&logoColor=lightblue"/></a><br/>
<a href="https://github.com/ArchiveBox/ArchiveBox/commits/dev"><img src="https://img.shields.io/github/last-commit/ArchiveBox/ArchiveBox.svg?logo=Sublime+Text&logoColor=green&label=active"/></a>
<a href="https://lgtm.com/projects/g/ArchiveBox/ArchiveBox/context:python"><img alt="Language grade: Python" src="https://img.shields.io/lgtm/grade/python/g/ArchiveBox/ArchiveBox.svg?logo=lgtm&logoWidth=18"/></a>
<a href="https://lgtm.com/projects/g/ArchiveBox/ArchiveBox/context:javascript"><img alt="Language grade: JavaScript" src="https://img.shields.io/lgtm/grade/javascript/g/ArchiveBox/ArchiveBox.svg?logo=lgtm&logoWidth=18"/></a>
<a href="https://lgtm.com/projects/g/ArchiveBox/ArchiveBox/alerts/"><img alt="Total alerts" src="https://img.shields.io/lgtm/alerts/g/ArchiveBox/ArchiveBox.svg?logo=lgtm&logoWidth=18"/></a>


<hr/>
</div>

ArchiveBox is a powerful self-hosted internet archiving solution written in Python. You feed it URLs of pages you want to archive, and it saves them to disk in a variety of formats depending on setup and content within.

**🔢&nbsp; Run ArchiveBox via [Docker Compose (recommended)](#Quickstart), Docker, Apt, Brew, or Pip ([see below](#Quickstart)).**

```bash
apt/brew/pip3 install archivebox

archivebox init                       # run this in an empty folder
archivebox add 'https://example.com'  # start adding URLs to archive
curl https://example.com/rss.xml | archivebox add  # or add via stdin
archivebox schedule --every=day https://example.com/rss.xml
```

For each URL added, ArchiveBox saves several types of HTML snapshot (wget, Chrome headless, singlefile), a PDF, a screenshot, a WARC archive, any git repositories, images, audio, video, subtitles, article text, [and more...](#output-formats).

```bash
archivebox server --createsuperuser 0.0.0.0:8000   # use the interactive web UI
archivebox list 'https://example.com'  # use the CLI commands (--help for more)
ls ./archive/*/index.json              # or browse directly via the filesystem
```

You can then manage your snapshots via the [filesystem](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#disk-layout), [CLI](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#CLI-Usage), [Web UI](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#UI-Usage), [SQLite DB](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/core/models.py) (`./index.sqlite3`), [Python API](https://docs.archivebox.io/en/latest/modules.html) (alpha), [REST API](https://github.com/ArchiveBox/ArchiveBox/issues/496) (alpha), or [desktop app](https://github.com/ArchiveBox/electron-archivebox) (alpha).

At the end of the day, the goal is to sleep soundly knowing that the part of the internet you care about will be automatically preserved in multiple, durable long-term formats that will be accessible for decades (or longer).

<div align="center">
<br/><br/>
<img src="https://i.imgur.com/PAzXZE8.png" height="70px" alt="bookshelf graphic"> &nbsp; <img src="https://i.imgur.com/asPNk8n.png" height="75px" alt="logo" align="top"/> &nbsp; <img src="https://i.imgur.com/PAzXZE8.png" height="70px" alt="bookshelf graphic">
<br/><br/>
</div>

#### ⚡️&nbsp; CLI Usage

```bash
# archivebox [subcommand] [--args]
archivebox --version
archivebox help
```

- `archivebox init/version/status/config/manage` to administer your collection
- `archivebox add/remove/update/list` to manage Snapshots in the archive
- `archivebox schedule` to pull in fresh URLs in regularly from [boorkmarks/history/Pocket/Pinboard/RSS/etc.](#input-formats)
- `archivebox oneshot` archive single URLs without starting a whole collection
- `archivebox shell/manage dbshell` open a REPL to use the [Python API](https://docs.archivebox.io/en/latest/modules.html) (alpha), or SQL API

<div align="center">
<br/>
<sup><a href="https://archivebox.zervice.io/">Demo</a> | <a href="#screenshots">Screenshots</a> | <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage">Usage</a></sup>
<br/>
<sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub>
<br/><br/>
<img src="https://i.imgur.com/njxgSbl.png" width="22%" alt="cli init screenshot" align="top">
<img src="https://i.imgur.com/lUuicew.png" width="22%" alt="cli init screenshot" align="top">
<img src="https://i.imgur.com/p6wK6KM.png" width="22%" alt="server snapshot admin screenshot" align="top">
<img src="https://i.imgur.com/xHvQfon.png" width="28.6%" alt="server snapshot details page screenshot" align="top"/>
<br/>
<br/>
<img src="https://i.imgur.com/T2UAGUD.png" width="49%" alt="grass"/><img src="https://i.imgur.com/T2UAGUD.png" width="49%" alt="grass"/>
</div>


### Quickstart

**🖥&nbsp; Supported OSs:** Linux/BSD, macOS, Windows  &nbsp; &nbsp; **🎮&nbsp; CPU Architectures:** x86, amd64, arm7, arm8 (raspi >=3)
**📦&nbsp; Distributions:** `docker`/`apt`/`brew`/`pip3`/`npm` (in order of completeness)

*(click to expand your preferred **► `distribution`** below for full setup instructions)*

<details>
<summary><b>Get ArchiveBox with <code>docker-compose</code> on any platform (recommended, everything included out-of-the-box)</b></summary>

<i>First make sure you have Docker installed: https://docs.docker.com/get-docker/</i>

<pre lang="bash"><code>
# create a new empty directory and initalize your collection (can be anywhere)
mkdir ~/archivebox && cd ~/archivebox
curl -O 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/master/docker-compose.yml'
docker-compose run archivebox init
docker-compose run archivebox --version

# start the webserver and open the UI (optional)
docker-compose run archivebox manage createsuperuser
docker-compose up -d
open 'http://127.0.0.1:8000'

# you can also add links and manage your archive via the CLI:
docker-compose run archivebox add 'https://example.com'
docker-compose run archivebox status
docker-compose run archivebox help  # to see more options
</code></pre>

This is the recommended way to run ArchiveBox because it includes <i>all</i> the extractors like:<br/>
chrome, wget, youtube-dl, git, etc., full-text search w/ sonic, and many other great features.

</details>

<details>
<summary><b>Get ArchiveBox with <code>docker</code> on any platform</b></summary>

<i>First make sure you have Docker installed: https://docs.docker.com/get-docker/</i>

<pre lang="bash"><code>
# create a new empty directory and initalize your collection (can be anywhere)
mkdir ~/archivebox && cd ~/archivebox
docker run -v $PWD:/data -it archivebox/archivebox init
docker run -v $PWD:/data -it archivebox/archivebox --version

# start the webserver and open the UI (optional)
docker run -v $PWD:/data -it -p 8000:8000 archivebox/archivebox server --createsuperuser 0.0.0.0:8000
open http://127.0.0.1:8000

# you can also add links and manage your archive via the CLI:
docker run -v $PWD:/data -it archivebox/archivebox add 'https://example.com'
docker run -v $PWD:/data -it archivebox/archivebox status
docker run -v $PWD:/data -it archivebox/archivebox help  # to see more options
</code></pre>

</details>

<details>
<summary><b>Get ArchiveBox with <code>apt</code> on Ubuntu >=20.04</b></summary>

<i>First make sure you're on Ubuntu >= 20.04, or scroll down for older/non-Ubuntu instructions.</i>

<pre lang="bash"><code>
# add the repo to your sources and install the archivebox package using apt
sudo apt install software-properties-common
sudo add-apt-repository -u ppa:archivebox/archivebox
sudo apt install archivebox

# create a new empty directory and initalize your collection (can be anywhere)
mkdir ~/archivebox && cd ~/archivebox
npm install --prefix . 'git+https://github.com/ArchiveBox/ArchiveBox.git'
archivebox init
archivebox --version

# start the webserver and open the web UI (optional)
archivebox server --createsuperuser 0.0.0.0:8000
open http://127.0.0.1:8000

# you can also add URLs and manage the archive via the CLI and filesystem:
archivebox add 'https://example.com'
archivebox status
archivebox list --html --with-headers > index.html
archivebox list --json --with-headers > index.json
archivebox help  # to see more options
</code></pre>

For other Debian-based systems or older Ubuntu systems you can add these sources to `/etc/apt/sources.list`:

<pre lang="bash"><code>
deb http://ppa.launchpad.net/archivebox/archivebox/ubuntu focal main
deb-src http://ppa.launchpad.net/archivebox/archivebox/ubuntu focal main
</code></pre>

Then run `apt update; apt install archivebox; archivebox --version`.

(you may need to install some other dependencies manually however)

</details>

<details>
<summary><b>Get ArchiveBox with <code>brew</code> on macOS >=10.13</b></summary>

<i>First make sure you have Homebrew installed: https://brew.sh/#install</i>

<pre lang="bash"><code>
# install the archivebox package using homebrew
brew install archivebox/archivebox/archivebox

# create a new empty directory and initalize your collection (can be anywhere)
mkdir ~/archivebox && cd ~/archivebox
npm install --prefix . 'git+https://github.com/ArchiveBox/ArchiveBox.git'
archivebox init
archivebox --version

# start the webserver and open the web UI (optional)
archivebox server --createsuperuser 0.0.0.0:8000
open http://127.0.0.1:8000

# you can also add URLs and manage the archive via the CLI and filesystem:
archivebox add 'https://example.com'
archivebox status
archivebox list --html --with-headers > index.html
archivebox list --json --with-headers > index.json
archivebox help  # to see more options
</code></pre>

</details>

<details>
<summary><b>Get ArchiveBox with <code>pip</code> on any platform</b></summary>

<i>First make sure you have Python >= 3.7 installed: https://realpython.com/installing-python/</i>

<pre lang="bash"><code>
# install the archivebox package using pip3
pip3 install archivebox

# create a new empty directory and initalize your collection (can be anywhere)
mkdir ~/archivebox && cd ~/archivebox
npm install --prefix . 'git+https://github.com/ArchiveBox/ArchiveBox.git'
archivebox init
archivebox --version
# Install any missing extras like wget/git/chrome/etc. manually as needed

# start the webserver and open the web UI (optional)
archivebox server --createsuperuser 0.0.0.0:8000
open http://127.0.0.1:8000

# you can also add URLs and manage the archive via the CLI and filesystem:
archivebox add 'https://example.com'
archivebox status
archivebox list --html --with-headers > index.html
archivebox list --json --with-headers > index.json
archivebox help  # to see more options
</code></pre>

</details>

No matter which install method you choose, they all roughly follow this 3-step process and all provide the same CLI, Web UI, and on-disk data format.

<small>

1. Install ArchiveBox: `apt/brew/pip3 install archivebox`
2. Start a collection: `archivebox init`
3. Start archiving: `archivebox add 'https://example.com'`

</small>

<br/>
<div align="center">
<img src="https://i.imgur.com/6AmOGJT.png" width="49%" alt="grass"/><img src="https://i.imgur.com/6AmOGJT.png" width="49%" alt="grass"/>
</div>
<br/>

<div align="center">
<br/>
<sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub>
<br/><br/>
<a href="https://archivebox.zervice.io">DEMO: <code>https://archivebox.zervice.io</code></a><br/>
<a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart">Quickstart</a> | <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage">Usage</a> | <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration">Configuration</a>
<br/>
</div>

## Key Features

- [**Free & open source**](https://github.com/ArchiveBox/ArchiveBox/blob/master/LICENSE), doesn't require signing up for anything, stores all data locally
- [**Powerful, intuitive command line interface**](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#CLI-Usage) with [modular optional dependencies](#dependencies) 
- [**Comprehensive documentation**](https://github.com/ArchiveBox/ArchiveBox/wiki), [active development](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap), and [rich community](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community)
- [**Extracts a wide variety of content out-of-the-box**](https://github.com/ArchiveBox/ArchiveBox/issues/51): [media (youtube-dl), articles (readability), code (git), etc.](#output-formats)
- [**Supports scheduled/realtime importing**](https://github.com/ArchiveBox/ArchiveBox/wiki/Scheduled-Archiving) from [many types of sources](#input-formats)
- [**Uses standard, durable, long-term formats**](#saves-lots-of-useful-stuff-for-each-imported-link) like HTML, JSON, PDF, PNG, and WARC
- [**Usable as a oneshot CLI**](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#CLI-Usage), [**self-hosted web UI**](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#UI-Usage), [Python API](https://docs.archivebox.io/en/latest/modules.html) (BETA), [REST API](https://github.com/ArchiveBox/ArchiveBox/issues/496) (ALPHA), or [desktop app](https://github.com/ArchiveBox/electron-archivebox) (ALPHA)
- [**Saves all pages to archive.org as well**](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#submit_archive_dot_org) by default for redundancy (can be [disabled](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#stealth-mode) for local-only mode)
- Planned: support for archiving [content requiring a login/paywall/cookies](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#chrome_user_data_dir) (working, but ill-advised until some pending fixes are released)
- Planned: support for running [JS scripts during archiving](https://github.com/ArchiveBox/ArchiveBox/issues/51), e.g. adblock, [autoscroll](https://github.com/ArchiveBox/ArchiveBox/issues/80), [modal-hiding](https://github.com/ArchiveBox/ArchiveBox/issues/175), [thread-expander](https://github.com/ArchiveBox/ArchiveBox/issues/345), etc.

<br/>

---

<div align="center">
<img src="https://i.imgur.com/OUmgdlH.png" width="96%" alt="lego">
</div>

## Input formats

ArchiveBox supports many input formats for URLs, including Pocket & Pinboard exports, Browser bookmarks, Browser history, plain text, HTML, markdown, and more!

```bash
echo 'http://example.com' | archivebox add
archivebox add 'https://example.com/some/page'
archivebox add < ~/Downloads/firefox_bookmarks_export.html
archivebox add < any_text_with_urls_in_it.txt
archivebox add --depth=1 'https://example.com/some/downloads.html'
archivebox add --depth=1 'https://news.ycombinator.com#2020-12-12'
```


- <img src="https://nicksweeting.com/images/rss.svg" height="22px"/> TXT, RSS, XML, JSON, CSV, SQL, HTML, Markdown, or [any other text-based format...](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#Import-a-list-of-URLs-from-a-text-file)
- <img src="https://nicksweeting.com/images/bookmarks.png" height="22px"/> [Browser history](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive) or [browser bookmarks](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive) (see instructions for: [Chrome](https://support.google.com/chrome/answer/96816?hl=en), [Firefox](https://support.mozilla.org/en-US/kb/export-firefox-bookmarks-to-backup-or-transfer), [Safari](http://i.imgur.com/AtcvUZA.png), [IE](https://support.microsoft.com/en-us/help/211089/how-to-import-and-export-the-internet-explorer-favorites-folder-to-a-32-bit-version-of-windows), [Opera](http://help.opera.com/Windows/12.10/en/importexport.html), [and more...](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive))
- <img src="https://getpocket.com/favicon.ico" height="22px"/> [Pocket](https://getpocket.com/export), [Pinboard](https://pinboard.in/export/), [Instapaper](https://www.instapaper.com/user/export), [Shaarli](https://shaarli.readthedocs.io/en/master/Usage/#importexport), [Delicious](https://www.groovypost.com/howto/howto/export-delicious-bookmarks-xml/), [Reddit Saved](https://github.com/csu/export-saved-reddit), [Wallabag](https://doc.wallabag.org/en/user/import/wallabagv2.html), [Unmark.it](http://help.unmark.it/import-export), [OneTab](https://www.addictivetips.com/web/onetab-save-close-all-chrome-tabs-to-restore-export-or-import/), [and more...](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive)

See the [Usage: CLI](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#CLI-Usage) page for documentation and examples.

It also includes a built-in scheduled import feature with `archivebox schedule` and browser bookmarklet, so you can pull in URLs from RSS feeds, websites, or the filesystem regularly/on-demand.

## Output formats

All of ArchiveBox's state (including the index, snapshot data, and config file) is stored in a single folder called the "ArchiveBox data folder". All `archivebox` CLI commands must be run from inside this folder, and you first create it by running `archivebox init`.

The on-disk layout is optimized to be easy to browse by hand and durable long-term. The main index is a standard sqlite3 database (it can also be exported as static JSON/HTML), and the archive snapshots are organized by date-added timestamp in the `archive/` subfolder. Each snapshot subfolder includes a static JSON and HTML index describing its contents, and the snapshot extrator outputs are plain files within the folder (e.g. `media/example.mp4`, `git/somerepo.git`, `static/someimage.png`, etc.)

```bash
# to browse your index statically without running the archivebox server, run:
archivebox list --html --with-headers > index.html
archivebox list --json --with-headers > index.json

# then open the static index in a browser
open index.html

# or browse the snapshots via filesystem directly
ls ./archive/<timestamp>/
```

- **Index:** `index.html` & `index.json` HTML and JSON index files containing metadata and details
- **Title**, **Favicon**, **Headers** Response headers, site favicon, and parsed site title
- **Wget Clone:** `example.com/page-name.html` wget clone of the site with  `warc/<timestamp>.gz`
- Chrome Headless
  - **SingleFile:** `singlefile.html` HTML snapshot rendered with headless Chrome using SingleFile
  - **PDF:** `output.pdf` Printed PDF of site using headless chrome
  - **Screenshot:** `screenshot.png` 1440x900 screenshot of site using headless chrome
  - **DOM Dump:** `output.html` DOM Dump of the HTML after rendering using headless chrome
  - **Readability:** `article.html/json` Article text extraction using Readability
- **Archive.org Permalink:** `archive.org.txt` A link to the saved site on archive.org
- **Audio & Video:** `media/` all audio/video files + playlists, including subtitles & metadata with youtube-dl
- **Source Code:** `git/` clone of any repository found on github, bitbucket, or gitlab links
- _More coming soon! See the [Roadmap](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap)..._

It does everything out-of-the-box by default, but you can disable or tweak [individual archive methods](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration) via environment variables or config file.

```bash
archivebox config --set SAVE_ARCHIVE_DOT_ORG=False
archivebox config --set YOUTUBEDL_ARGS='--max-filesize=500m'
archivebox config --help
```

<div align="center">
<img src="https://i.imgur.com/ucyimDX.png" width="96%" alt="lego graphic">
</div>

<br/>

---

<br/>

## Dependencies

You don't need to install all the dependencies, ArchiveBox will automatically enable the relevant modules based on whatever you have available, but it's recommended to use the official [Docker image](https://github.com/ArchiveBox/ArchiveBox/wiki/Docker) with everything preinstalled.

If you so choose, you can also install ArchiveBox and its dependencies directly on any Linux or macOS systems using the [system package manager](https://github.com/ArchiveBox/ArchiveBox/wiki/Install) or by running the [automated setup script](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart).

ArchiveBox is written in Python 3 so it requires `python3` and `pip3` available on your system. It also uses a set of optional, but highly recommended external dependencies for archiving sites: `wget` (for plain HTML, static files, and WARC saving), `chromium` (for screenshots, PDFs, JS execution, and more), `youtube-dl` (for audio and video), `git` (for cloning git repos), and `nodejs` (for readability and singlefile), and more.

<br/>

---

<div align="center">
<img src="https://docs.monadical.com/uploads/upload_b6900afc422ae699bfefa2dcda3306f3.png" width="100%" alt="security graphic"/>
</div>

## Caveats

If you're importing URLs containing secret slugs or pages with private content (e.g Google Docs, CodiMD notepads, etc), you may want to disable some of the extractor modules to avoid leaking private URLs to 3rd party APIs during the archiving process.

```bash
# don't do this:
archivebox add 'https://docs.google.com/document/d/12345somelongsecrethere'
archivebox add 'https://example.com/any/url/you/want/to/keep/secret/'

# without first disabling share the URL with 3rd party APIs:
archivebox config --set SAVE_ARCHIVE_DOT_ORG=False   # disable saving all URLs in Archive.org
archivebox config --set SAVE_FAVICON=False      # optional: only the domain is leaked, not full URL
archivebox config --set CHROME_BINARY=chromium  # optional: switch to chromium to avoid Chrome phoning home to Google
```

Be aware that malicious archived JS can also read the contents of other pages in your archive due to snapshot CSRF and XSS protections being imperfect. See the [Security Overview](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#stealth-mode) page for more details.

```bash
# visiting an archived page with malicious JS:
https://127.0.0.1:8000/archive/1602401954/example.com/index.html

# example.com/index.js can now make a request to read everything:
https://127.0.0.1:8000/index.html
https://127.0.0.1:8000/archive/*
# then example.com/index.js can send it off to some evil server
```

Support for saving multiple snapshots of each site over time will be [added soon](https://github.com/ArchiveBox/ArchiveBox/issues/179) (along with the ability to view diffs of the changes between runs). For now ArchiveBox is designed to only archive each URL with each extractor type once. A workaround to take multiple snapshots of the same URL is to make them slightly different by adding a hash:

```bash
archivebox add 'https://example.com#2020-10-24'
...
archivebox add 'https://example.com#2020-10-25'
```

<br/>

---

<br/>

## Screenshots

<div align="center" width="80%">
<img src="https://i.imgur.com/PVO88AZ.png" width="80%"/>
<table>
<tbody>
<tr>
<td>
<img src="https://i.imgur.com/npareKG.png" alt="brew install archivebox"><br/>
<img src="https://i.imgur.com/5vSBO2R.png" alt="archivebox version">
</td>
<td>
<img src="https://i.imgur.com/JXXxFzB.png" alt="archivebox init"><br/>
</td>
<td>
<img src="https://i.imgur.com/wNYtV3v.jpg" alt="archivebox add">
</td>
<td>
<img src="https://i.imgur.com/uZcIOn9.png" alt="archivebox data dir">
</td>
</tr>
<tr>
<td>
<img src="https://i.imgur.com/H08eaia.png" alt="archivebox server">
</td>
<td>
<img src="https://i.imgur.com/zM4z1aU.png" alt="archivebox server add">
</td>
<td>
<img src="https://i.imgur.com/p6wK6KM.png" alt="archivebox server list">
</td>
<td>
<img src="https://i.imgur.com/xHvQfon.png" alt="archivebox server detail">
</td>
</tr>
</tbody>
</table>
</div>
<br/>

---

<br/>

<div align="center">
<img src="https://i.imgur.com/ZSUm9mr.png" width="100%" alt="paisley graphic">
</div>

# Background & Motivation

Vast treasure troves of knowledge are lost every day on the internet to link rot. As a society, we have an imperative to preserve some important parts of that treasure, just like we preserve our books, paintings, and music in physical libraries long after the originals go out of print or fade into obscurity.

Whether it's to resist censorship by saving articles before they get taken down or edited, or
just to save a collection of early 2010's flash games you love to play, having the tools to
archive internet content enables to you save the stuff you care most about before it disappears.

<div align="center">
<img src="https://i.imgur.com/bC6eZcV.png" width="50%"/><br/>
 <sup><i>Image from <a href="https://digiday.com/media/wtf-link-rot/">WTF is Link Rot?</a>...</i><br/></sup>
</div>

The balance between the permanence and ephemeral nature of content on the internet is part of what makes it beautiful.
I don't think everything should be preserved in an automated fashion, making all content permanent and never removable, but I do think people should be able to decide for themselves and effectively archive specific content that they care about.

Because modern websites are complicated and often rely on dynamic content,
ArchiveBox archives the sites in **several different formats** beyond what public archiving services like Archive.org and Archive.is are capable of saving. Using multiple methods and the market-dominant browser to execute JS ensures we can save even the most complex, finicky websites in at least a few high-quality, long-term data formats.

All the archived links are stored by date bookmarked in `./archive/<timestamp>`, and everything is indexed nicely with JSON & HTML files. The intent is for all the content to be viewable with common software in 50 - 100 years without needing to run ArchiveBox in a VM.

## Comparison to Other Projects

▶ **Check out our [community page](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community) for an index of web archiving initiatives and projects.**

<img src="https://i.imgur.com/4nkFjdv.png" width="10%" align="left" alt="comparison"/> The aim of ArchiveBox is to go beyond what the Wayback Machine and other public archiving services can do, by adding a headless browser to replay sessions accurately, and by automatically extracting all the content in multiple redundant formats that will survive being passed down to historians and archivists through many generations.

#### User Interface & Intended Purpose

ArchiveBox differentiates itself from [similar projects](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#Web-Archiving-Projects) by being a simple, one-shot CLI interface for users to ingest bulk feeds of URLs over extended periods, as opposed to being a backend service that ingests individual, manually-submitted URLs from a web UI. However, we also have the option to add urls via a web interface through our Django frontend.

#### Private Local Archives vs Centralized Public Archives

Unlike crawler software that starts from a seed URL and works outwards, or public tools like Archive.org designed for users to manually submit links from the public internet, ArchiveBox tries to be a set-and-forget archiver suitable for archiving your entire browsing history, RSS feeds, or bookmarks, ~~including private/authenticated content that you wouldn't otherwise share with a centralized service~~ (do not do this until v0.5 is released with some security fixes). Also by having each user store their own content locally, we can save much larger portions of everyone's browsing history than a shared centralized service would be able to handle.

#### Storage Requirements

Because ArchiveBox is designed to ingest a firehose of browser history and bookmark feeds to a local disk, it can be much more disk-space intensive than a centralized service like the Internet Archive or Archive.today. However, as storage space gets cheaper and compression improves, you should be able to use it continuously over the years without having to delete anything. In my experience, ArchiveBox uses about 5gb per 1000 articles, but your milage may vary depending on which options you have enabled and what types of sites you're archiving. By default, it archives everything in as many formats as possible, meaning it takes more space than a using a single method, but more content is accurately replayable over extended periods of time. Storage requirements can be reduced by using a compressed/deduplicated filesystem like ZFS/BTRFS, or by setting `SAVE_MEDIA=False` to skip audio & video files.

<div align="center">
<br/>
<img src="https://i.imgur.com/q0Oe36M.png" width="100%" alt="dependencies graphic">
</div>

## Learn more

Whether you want to learn which organizations are the big players in the web archiving space, want to find a specific open-source tool for your web archiving need, or just want to see where archivists hang out online, our Community Wiki page serves as an index of the broader web archiving community. Check it out to learn about some of the coolest web archiving projects and communities on the web!

<img src="https://i.imgur.com/0ZOmOvN.png" width="14%" align="right"/>

- [Community Wiki](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community)
  - [The Master Lists](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#the-master-lists)  
    _Community-maintained indexes of archiving tools and institutions._
  - [Web Archiving Software](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#web-archiving-projects)  
    _Open source tools and projects in the internet archiving space._
  - [Reading List](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#reading-list)  
    _Articles, posts, and blogs relevant to ArchiveBox and web archiving in general._
  - [Communities](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#communities)  
    _A collection of the most active internet archiving communities and initiatives._
- Check out the ArchiveBox [Roadmap](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap) and [Changelog](https://github.com/ArchiveBox/ArchiveBox/wiki/Changelog)
- Learn why archiving the internet is important by reading the "[On the Importance of Web Archiving](https://parameters.ssrc.org/2018/09/on-the-importance-of-web-archiving/)" blog post.
- Or reach out to me for questions and comments via [@ArchiveBoxApp](https://twitter.com/ArchiveBoxApp) or [@theSquashSH](https://twitter.com/thesquashSH) on Twitter.

<br/>

---

<div align="center">
<img src="https://i.imgur.com/SMkGW0L.png" width="100%" alt="documentation graphic">
</div>

# Documentation

<img src="https://read-the-docs-guidelines.readthedocs-hosted.com/_images/logo-dark.png" width="13%" align="right"/>

We use the [Github wiki system](https://github.com/ArchiveBox/ArchiveBox/wiki) and [Read the Docs](https://archivebox.readthedocs.io/en/latest/) (WIP) for documentation.

You can also access the docs locally by looking in the [`ArchiveBox/docs/`](https://github.com/ArchiveBox/ArchiveBox/wiki/Home) folder.

## Getting Started

- [Quickstart](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart)
- [Install](https://github.com/ArchiveBox/ArchiveBox/wiki/Install)
- [Docker](https://github.com/ArchiveBox/ArchiveBox/wiki/Docker)

## Reference

- [Usage](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage)
- [Configuration](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration)
- [Supported Sources](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive)
- [Supported Outputs](https://github.com/ArchiveBox/ArchiveBox/wiki#can-save-these-things-for-each-site)
- [Scheduled Archiving](https://github.com/ArchiveBox/ArchiveBox/wiki/Scheduled-Archiving)
- [Publishing Your Archive](https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive)
- [Chromium Install](https://github.com/ArchiveBox/ArchiveBox/wiki/Chromium-Install)
- [Security Overview](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview)
- [Troubleshooting](https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting)
- [Python API](https://docs.archivebox.io/en/latest/modules.html) (alpha)
- [REST API](https://github.com/ArchiveBox/ArchiveBox/issues/496) (alpha)

## More Info

- [Tickets](https://github.com/ArchiveBox/ArchiveBox/issues)
- [Roadmap](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap)
- [Changelog](https://github.com/ArchiveBox/ArchiveBox/wiki/Changelog)
- [Donations](https://github.com/ArchiveBox/ArchiveBox/wiki/Donations)
- [Background & Motivation](https://github.com/ArchiveBox/ArchiveBox#background--motivation)
- [Web Archiving Community](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community)

<br/>

---

<div align="center">
<img src="https://i.imgur.com/EGWjbD4.png" width="100%" alt="development">
</div>

# ArchiveBox Development

All contributions to ArchiveBox are welcomed! Check our [issues](https://github.com/ArchiveBox/ArchiveBox/issues) and [Roadmap](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap) for things to work on, and please open an issue to discuss your proposed implementation before working on things! Otherwise we may have to close your PR if it doesn't align with our roadmap.

Low hanging fruit / easy first tickets:<br/>
<a href="https://lgtm.com/projects/g/ArchiveBox/ArchiveBox/alerts/"><img alt="Total alerts" src="https://img.shields.io/lgtm/alerts/g/ArchiveBox/ArchiveBox.svg?logo=lgtm&logoWidth=18"/></a>

### Setup the dev environment

#### 1. Clone the main code repo (making sure to pull the submodules as well)

```bash
git clone --recurse-submodules https://github.com/ArchiveBox/ArchiveBox
cd ArchiveBox
git checkout dev  # or the branch you want to test
git submodule update --init --recursive
git pull --recurse-submodules
```

#### 2. Option A: Install the Python, JS, and system dependencies directly on your machine

```bash
# Install ArchiveBox + python dependencies
python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'
# or: pipenv install --dev && pipenv shell

# Install node dependencies
npm install

# Check to see if anything is missing
archivebox --version
# install any missing dependencies manually, or use the helper script:
./bin/setup.sh
```

#### 2. Option B: Build the docker container and use that for development instead

```bash
# Optional: develop via docker by mounting the code dir into the container
# if you edit e.g. ./archivebox/core/models.py on the docker host, runserver
# inside the container will reload and pick up your changes
docker build . -t archivebox
docker run -it --rm archivebox version
docker run -it --rm -p 8000:8000 \
    -v $PWD/data:/data \
    -v $PWD/archivebox:/app/archivebox \
    archivebox server 0.0.0.0:8000 --debug --reload
```

### Common development tasks

See the `./bin/` folder and read the source of the bash scripts within.
You can also run all these in Docker. For more examples see the Github Actions CI/CD tests that are run: `.github/workflows/*.yaml`.

#### Run in DEBUG mode

```bash
archivebox config --set DEBUG=True
# or
archivebox server --debug ...
```

#### Build and run a Github branch

```bash
docker build -t archivebox:dev https://github.com/ArchiveBox/ArchiveBox.git#dev
docker run -it -v $PWD:/data archivebox:dev ...
```

#### Run the linters

```bash
./bin/lint.sh
```
(uses `flake8` and `mypy`)

#### Run the integration tests

```bash
./bin/test.sh
```
(uses `pytest -s`)

#### Make migrations or enter a django shell

Make sure to run this whenever you change things in `models.py`.
```bash
cd archivebox/
./manage.py makemigrations

cd path/to/test/data/
archivebox shell
archivebox manage dbshell
```
(uses `pytest -s`)

#### Build the docs, pip package, and docker image

(Normally CI takes care of this, but these scripts can be run to do it manually)
```bash
./bin/build.sh

# or individually:
./bin/build_docs.sh
./bin/build_pip.sh
./bin/build_deb.sh
./bin/build_brew.sh
./bin/build_docker.sh
```

#### Roll a release

(Normally CI takes care of this, but these scripts can be run to do it manually)
```bash
./bin/release.sh

# or individually:
./bin/release_docs.sh
./bin/release_pip.sh
./bin/release_deb.sh
./bin/release_brew.sh
./bin/release_docker.sh
```

---

<div align="center">
<br/><br/>
<img src="https://raw.githubusercontent.com/Monadical-SAS/redux-time/HEAD/examples/static/jeremy.jpg" height="40px"/>
<br/>
<sub><i>This project is maintained mostly in <a href="https://nicksweeting.com/blog#About">my spare time</a> with the help from generous contributors and Monadical.com.</i></sub>
<br/><br/>

<br/>
<a href="https://github.com/sponsors/pirate">Sponsor us on Github</a>
<br>
<br>
<a href="https://www.patreon.com/theSquashSH"><img src="https://img.shields.io/badge/Donate_to_support_development-via_Patreon-%23DD5D76.svg?style=flat"/></a>
<br/>

<a href="https://twitter.com/ArchiveBoxApp"><img src="https://img.shields.io/badge/Tweet-%40ArchiveBoxApp-blue.svg?style=flat"/></a>
<a href="https://github.com/ArchiveBox/ArchiveBox"><img src="https://img.shields.io/github/stars/ArchiveBox/ArchiveBox.svg?style=flat&label=Star+on+Github"/></a>

<br/><br/>

</div>
