<div align="center">
<em><img src="https://i.imgur.com/5B48E3N.png" height="90px"></em>
<h1>ArchiveBox<br/><sub>Open-source self-hosted web archiving.</sub></h1>

▶️ <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart">Quickstart</a> |
<a href="https://demo.archivebox.io">Demo</a> |
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

ArchiveBox is a powerful internet archiving solution that works like a self-hosted Wayback Machine. You feed it URLs of pages you want to archive, and it saves them locally in a variety of formats depending on setup and content within.

It supports taking URLs in one at a time, or scheduled importing from browser bookmarks/history, RSS, services like Pocket/Pinboard and more. For a full list see <a href="#input-formats">input formats</a>.

It saves snapshots of the URLs you feed it as HTML, PDF, PNG screenshots, WARC, and more out-of-the-box, with a wide variety of content extracted and preserved automatically (article text, audio/video, git repos, etc.). See <a href="#output-formats">output formats</a> for a full list.

At the end of the day, the goal is to sleep soundly knowing the part of the internet you care about will be automatically preserved on your own machine. By saving sites in multiple, durable, long-term formats it ensures that content will be accessible and sharable for many decades to come without needing ArchiveBox or other specialized software to access it.

<div align="center">
<br/><br/>
<img src="https://i.imgur.com/PAzXZE8.png" height="70px" alt="bookshelf graphic"> &nbsp; <img src="https://i.imgur.com/asPNk8n.png" height="75px" alt="logo" align="top"/> &nbsp; <img src="https://i.imgur.com/PAzXZE8.png" height="70px" alt="bookshelf graphic">
<br/><br/>
<small><a href="https://demo.archivebox.io">Demo</a> | <a href="#screenshots">Screenshots</a> | <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage">Usage</a></small>
<br/>
<sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub>
<br/><br/>
</div>

<br/>

**📦&nbsp; First, get ArchiveBox using [Docker Compose (recommended)](#Quickstart), or Docker, Apt, Brew, Pip ([see the instructions below for your OS](#Quickstart)).**

*No matter which setup method you choose, they all follow this basic process and provide the same CLI, Web UI, and on-disk data layout.*

1. Run this in a new empty folder to get started
```bash
archivebox init --setup                   # creates a new collection in the current directory
```

2. Add some URLs you want to archive
```bash
archivebox add 'https://example.com'                                     # add URLs one at a time via args / piped stdin
archivebox schedule --every=day --depth=1 https://example.com/rss.xml    # or have it import URLs on a schedule
```

<sup>ArchiveBox will save HTML snapshots (w/ wget, Chrome headless, singlefile), a PDF, a screenshot, a WARC archive, article text, images, audio/video, subtitles, git repos, and more.</sup>

3. Then view your archived pages

```bash
archivebox server 0.0.0.0:8000            # use the interactive web UI
archivebox list 'https://example.com'     # use the CLI commands (--help for more)
ls ./archive/*/index.json                 # or browse directly via the filesystem
```

**⤵️ See the [Quickstart](#Quickstart) below for more...**

<div align="center">
<br/><br/>
<img src="https://i.imgur.com/njxgSbl.png" width="22%" alt="cli init screenshot" align="top">
<img src="https://i.imgur.com/lUuicew.png" width="22%" alt="cli init screenshot" align="top">
<img src="https://i.imgur.com/p6wK6KM.png" width="22%" alt="server snapshot admin screenshot" align="top">
<img src="https://i.imgur.com/xHvQfon.png" width="28.6%" alt="server snapshot details page screenshot" align="top"/>
<br/><br/>
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

<br/><br/>

<div align="center">
<br/>
<img src="https://i.imgur.com/T2UAGUD.png" width="49%" alt="grass"/><img src="https://i.imgur.com/T2UAGUD.png" width="49%" alt="grass"/>
</div>

# Quickstart

**🖥&nbsp; Supported OSs:** Linux/BSD, macOS, Windows (w/ Docker, WSL/WSL2)  &nbsp; &nbsp; **🎮&nbsp; CPU Architectures:** amd64, x86, arm8, arm7 (raspi >=3)


#### ⬇️&nbsp; Initial Setup

*(click to expand your preferred **► `distribution`** below for full setup instructions)*

<details>
<summary><b>Get ArchiveBox with <code>docker-compose</code> on macOS/Linux/Windows (recommended, everything included out-of-the-box ✨)</b></summary>

<i>First make sure you have Docker installed: https://docs.docker.com/get-docker/</i>

Download the [`docker-compose.yml`](https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/master/docker-compose.yml) file.
<pre lang="bash"><code style="white-space: pre-line">
curl -O 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/master/docker-compose.yml'
</code></pre>

Start the server.
<pre lang="bash"><code style="white-space: pre-line">
docker-compose run archivebox init --setup
docker-compose up
</code></pre>

Open [`http://127.0.0.1:8000`](http://127.0.0.1:8000).

<pre lang="bash"><code style="white-space: pre-line">
# you can also add links and manage your archive via the CLI:
docker-compose run archivebox add 'https://example.com'
echo 'https://example.com' | docker-compose run archivebox -T add
docker-compose run archivebox status
docker-compose run archivebox help  # to see more options

# when passing stdin/stdout via the cli, use the -T flag
echo 'https://example.com' | docker-compose run -T archivebox add
docker-compose run -T archivebox list --html --with-headers > index.html
</code></pre>

This is the recommended way to run ArchiveBox because it includes <i>all</i> the extractors like:<br/>
chrome, wget, youtube-dl, git, etc., full-text search w/ sonic, and many other great features.

</details>

<details>
<summary><b>Get ArchiveBox with <code>docker</code> on macOS/Linux/Windows</b></summary>

<i>First make sure you have Docker installed: https://docs.docker.com/get-docker/</i>

<pre lang="bash"><code style="white-space: pre-line">
# create a new empty directory and initalize your collection (can be anywhere)
mkdir ~/archivebox && cd ~/archivebox
docker run -v $PWD:/data -it archivebox/archivebox init --setup

# start the webserver and open the UI (optional)
docker run -v $PWD:/data -p 8000:8000 archivebox/archivebox server 0.0.0.0:8000
open http://127.0.0.1:8000

# you can also add links and manage your archive via the CLI:
docker run -v $PWD:/data -it archivebox/archivebox add 'https://example.com'
docker run -v $PWD:/data -it archivebox/archivebox status
docker run -v $PWD:/data -it archivebox/archivebox help  # to see more options

# when passing stdin/stdout via the cli, use only -i (not -it)
echo 'https://example.com' | docker run -v $PWD:/data -i archivebox/archivebox add
docker run -v $PWD:/data -i archivebox/archivebox list --html --with-headers > index.html
</code></pre>

</details>

<details>
<summary><b>Get ArchiveBox with <code>apt</code> on Ubuntu/Debian</b></summary>

This method should work on all Ubuntu/Debian based systems, including x86, amd64, arm7, and arm8 CPUs (e.g. Raspberry Pis >=3).

If you're on Ubuntu >= 20.04, add the `apt` repository with `add-apt-repository`:
<small><i>(on other Ubuntu/Debian-based systems follow the <b>♰ instructions</b> below)</i></small>

<pre lang="bash"><code style="white-space: pre-line">
# add the repo to your sources and install the archivebox package using apt
sudo apt install software-properties-common
sudo add-apt-repository -u ppa:archivebox/archivebox
sudo apt install archivebox
</code></pre>

<pre lang="bash"><code style="white-space: pre-line">
# create a new empty directory and initalize your collection (can be anywhere)
mkdir ~/archivebox && cd ~/archivebox
archivebox init --setup

# start the webserver and open the web UI (optional)
archivebox server 0.0.0.0:8000
open http://127.0.0.1:8000

# you can also add URLs and manage the archive via the CLI and filesystem:
archivebox add 'https://example.com'
archivebox status
archivebox list --html --with-headers > index.html
archivebox list --json --with-headers > index.json
archivebox help  # to see more options
</code></pre>

<i><b>♰ On other Ubuntu/Debian-based systems</b> add these sources directly to <code>/etc/apt/sources.list</code>:</i>

<pre lang="bash"><code style="white-space: pre-line">
echo "deb http://ppa.launchpad.net/archivebox/archivebox/ubuntu focal main" > /etc/apt/sources.list.d/archivebox.list
echo "deb-src http://ppa.launchpad.net/archivebox/archivebox/ubuntu focal main" >> /etc/apt/sources.list.d/archivebox.list
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys C258F79DCC02E369
sudo apt update
sudo apt install archivebox
sudo snap install chromium
archivebox --version
# then scroll back up and continue the initalization instructions above
</code></pre>

(you may need to install some other dependencies manually however)

</details>

<details>
<summary><b>Get ArchiveBox with <code>brew</code> on macOS</b></summary>

<i>First make sure you have Homebrew installed: https://brew.sh/#install</i>

<pre lang="bash"><code style="white-space: pre-line">
# install the archivebox package using homebrew
brew install archivebox/archivebox/archivebox

# create a new empty directory and initalize your collection (can be anywhere)
mkdir ~/archivebox && cd ~/archivebox
archivebox init --setup

# start the webserver and open the web UI (optional)
archivebox server 0.0.0.0:8000
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
<summary><b>Get ArchiveBox with <code>pip</code> on any other platforms</b></summary>

<i>First make sure you have [Python >= v3.7](https://realpython.com/installing-python/) and [Node >= v12](https://nodejs.org/en/download/package-manager/) installed.</i>

<pre lang="bash"><code style="white-space: pre-line">
# install the archivebox package using pip3
pip3 install archivebox

# create a new empty directory and initalize your collection (can be anywhere)
mkdir ~/archivebox && cd ~/archivebox
archivebox init --setup
# Install any missing extras like wget/git/ripgrep/etc. manually as needed

# start the webserver and open the web UI (optional)
archivebox server 0.0.0.0:8000
open http://127.0.0.1:8000

# you can also add URLs and manage the archive via the CLI and filesystem:
archivebox add 'https://example.com'
archivebox status
archivebox list --html --with-headers > index.html
archivebox list --json --with-headers > index.json
archivebox help  # to see more options
</code></pre>

</details>


#### ⚡️&nbsp; CLI Usage

```bash
# archivebox [subcommand] [--args]
archivebox --version
archivebox help
```

- `archivebox setup/init/config/status/manage` to administer your collection
- `archivebox add/remove/update/list` to manage Snapshots in the archive
- `archivebox schedule` to pull in fresh URLs in regularly from [boorkmarks/history/Pocket/Pinboard/RSS/etc.](#input-formats)
- `archivebox oneshot` archive single URLs without starting a whole collection
- `archivebox shell/manage dbshell` open a REPL to use the [Python API](https://docs.archivebox.io/en/latest/modules.html) (alpha), or SQL API


#### 🖥&nbsp; Web UI Usage

```bash
archivebox manage createsuperuser
archivebox server 0.0.0.0:8000
```
Then open http://127.0.0.1:8000 to view the UI.

```bash
# you can also configure whether or not login is required for most features
archivebox config --set PUBLIC_INDEX=False
archivebox config --set PUBLIC_SNAPSHOTS=False
archivebox config --set PUBLIC_ADD_VIEW=False
```

<br/>
<div align="center">
<img src="https://i.imgur.com/6AmOGJT.png" width="49%" alt="grass"/><img src="https://i.imgur.com/6AmOGJT.png" width="49%" alt="grass"/>
</div>
<br/>

<div align="center">
<sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub>
<br/><br/>
<a href="https://demo.archivebox.io">DEMO: <code>https://demo.archivebox.io</code></a><br/>
<a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage">Usage</a> | <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration">Configuration</a> | <a href="#Caveats">Caveats</a>
<br/>
</div>

<br/>

---

<div align="center">
<img src="https://i.imgur.com/OUmgdlH.png" width="96%" alt="lego">
</div>

<br/>

## Dependencies

You don't need to install all the dependencies, ArchiveBox will automatically enable the relevant modules based on whatever you have available, but it's recommended to use the official [Docker image](https://github.com/ArchiveBox/ArchiveBox/wiki/Docker) with everything preinstalled for the best experience.

You can also install ArchiveBox and its dependencies using your [system package manager](https://github.com/ArchiveBox/ArchiveBox/wiki/Install) or `pip` directly on any Linux or macOS system, or on Windows (advanced users only).

```bash
# install archivebox with your system package manager
# apt/brew/pip/etc install ... (see Quickstart instructions above)

archivebox setup       # auto install all the extractors and extras
archivebox --version   # see info and versions of installed dependencies
```

ArchiveBox is written in Python 3 so it requires `python3` and `pip3` are available on your system when not using Docker. The optional dependencies used for archiving sites include: `wget` (for plain HTML, static files, and WARC saving), `chromium` (for screenshots, PDFs, JS execution, and more), `youtube-dl` (for audio and video), `git` (for cloning git repos), and `nodejs` (for readability, mercury, and singlefile), and more.

<br/>

## Input formats

ArchiveBox supports many input formats for URLs, including Pocket & Pinboard exports, Browser bookmarks, Browser history, plain text, HTML, markdown, and more!


*Click these links for instructions on how to propare your links from these sources:*

- <img src="https://nicksweeting.com/images/rss.svg" height="22px"/> TXT, RSS, XML, JSON, CSV, SQL, HTML, Markdown, or [any other text-based format...](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#Import-a-list-of-URLs-from-a-text-file)
- <img src="https://nicksweeting.com/images/bookmarks.png" height="22px"/> [Browser history](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive) or [browser bookmarks](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive) (see instructions for: [Chrome](https://support.google.com/chrome/answer/96816?hl=en), [Firefox](https://support.mozilla.org/en-US/kb/export-firefox-bookmarks-to-backup-or-transfer), [Safari](http://i.imgur.com/AtcvUZA.png), [IE](https://support.microsoft.com/en-us/help/211089/how-to-import-and-export-the-internet-explorer-favorites-folder-to-a-32-bit-version-of-windows), [Opera](http://help.opera.com/Windows/12.10/en/importexport.html), [and more...](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive))
- <img src="https://getpocket.com/favicon.ico" height="22px"/> [Pocket](https://getpocket.com/export), [Pinboard](https://pinboard.in/export/), [Instapaper](https://www.instapaper.com/user/export), [Shaarli](https://shaarli.readthedocs.io/en/master/Usage/#importexport), [Delicious](https://www.groovypost.com/howto/howto/export-delicious-bookmarks-xml/), [Reddit Saved](https://github.com/csu/export-saved-reddit), [Wallabag](https://doc.wallabag.org/en/user/import/wallabagv2.html), [Unmark.it](http://help.unmark.it/import-export), [OneTab](https://www.addictivetips.com/web/onetab-save-close-all-chrome-tabs-to-restore-export-or-import/), [and more...](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive)

```bash
# archivebox add --help
echo 'http://example.com' | archivebox add
archivebox add 'https://example.com/some/page'
archivebox add < ~/Downloads/firefox_bookmarks_export.html
archivebox add < any_text_with_urls_in_it.txt
archivebox add --depth=1 'https://example.com/some/downloads.html'
archivebox add --depth=1 'https://news.ycombinator.com#2020-12-12'

# (if using docker add -i when passing via stdin)
echo 'https://example.com' | docker run -v $PWD:/data -i archivebox/archivebox add

# (if using docker-compose add -T when passing via stdin)
echo 'https://example.com' | docker-compose run -T archivebox add
```

See the [Usage: CLI](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#CLI-Usage) page for documentation and examples.

It also includes a built-in scheduled import feature with `archivebox schedule` and browser bookmarklet, so you can pull in URLs from RSS feeds, websites, or the filesystem regularly/on-demand.

<br/>

## Output formats

All of ArchiveBox's state (including the index, snapshot data, and config file) is stored in a single folder called the "ArchiveBox data folder". All `archivebox` CLI commands must be run from inside this folder, and you first create it by running `archivebox init`.


- **Index:** `index.html` & `index.json` HTML and JSON index files containing metadata and details
- **Title**, **Favicon**, **Headers** Response headers, site favicon, and parsed site title
- **SingleFile:** `singlefile.html` HTML snapshot rendered with headless Chrome using SingleFile
- **Wget Clone:** `example.com/page-name.html` wget clone of the site with  `warc/<timestamp>.gz`
- Chrome Headless
  - **PDF:** `output.pdf` Printed PDF of site using headless chrome
  - **Screenshot:** `screenshot.png` 1440x900 screenshot of site using headless chrome
  - **DOM Dump:** `output.html` DOM Dump of the HTML after rendering using headless chrome
- **Article Text:** `article.html/json` Article text extraction using Readability & Mercury
- **Archive.org Permalink:** `archive.org.txt` A link to the saved site on archive.org
- **Audio & Video:** `media/` all audio/video files + playlists, including subtitles & metadata with youtube-dl
- **Source Code:** `git/` clone of any repository found on github, bitbucket, or gitlab links
- _More coming soon! See the [Roadmap](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap)..._

It does everything out-of-the-box by default, but you can disable or tweak [individual archive methods](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration) via environment variables / config.

```bash
# archivebox config --help
archivebox config    # see all currently configured options
archivebox config --set SAVE_ARCHIVE_DOT_ORG=False
archivebox config --set YOUTUBEDL_ARGS='--max-filesize=500m'
```

The on-disk layout is optimized to be easy to browse by hand and durable long-term. The main index is a standard sqlite3 database (it can also be exported as static JSON/HTML), and the archive snapshots are organized by date-added timestamp in the `archive/` subfolder. Each snapshot subfolder includes a static JSON and HTML index describing its contents, and the snapshot extrator outputs are plain files within the folder (e.g. `media/example.mp4`, `git/somerepo.git`, `static/someimage.png`, etc.)

```bash
# to browse your index statically without running the archivebox server, run:
archivebox list --html --with-headers > index.html    # open index.html to view
archivebox list --json --with-headers > index.json

# (if using docker-compose, add the -T flag when piping)
docker-compose run -T archivebox list --csv > index.csv
```

<br/>

---

<div align="center">
<img src="https://docs.monadical.com/uploads/upload_b6900afc422ae699bfefa2dcda3306f3.png" width="100%" alt="security graphic"/>
</div>

## Caveats

#### Archiving Private URLs

If you're importing URLs containing secret slugs or pages with private content (e.g Google Docs, CodiMD notepads, etc), you may want to disable some of the extractor modules to avoid leaking private URLs to 3rd party APIs during the archiving process.

```bash
# don't do this:
archivebox add 'https://docs.google.com/document/d/12345somelongsecrethere'
archivebox add 'https://example.com/any/url/you/want/to/keep/secret/'

# without first disabling share the URL with 3rd party APIs:
archivebox config --set SAVE_ARCHIVE_DOT_ORG=False  # disable saving all URLs in Archive.org

# if extra paranoid or anti-google:
archivebox config --set SAVE_FAVICON=False          # disable favicon fetching (it calls a google API)
archivebox config --set CHROME_BINARY=chromium      # ensure it's using Chromium instead of Chrome
```

#### Security Risks of Viewing Archived JS

Be aware that malicious archived JS can access the contents of other pages in your archive when viewed. Because the Web UI serves all viewed snapshots from a single domain, they share a request context and typical CSRF/CORS/XSS/CSP protections do not work to prevent cross-site request attacks. See the [Security Overview](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#stealth-mode) page for more details.

```bash
# visiting an archived page with malicious JS:
https://127.0.0.1:8000/archive/1602401954/example.com/index.html

# example.com/index.js can now make a request to read everything from:
https://127.0.0.1:8000/index.html
https://127.0.0.1:8000/archive/*
# then example.com/index.js can send it off to some evil server
```

#### Saving Multiple Snapshots of a Single URL

Support for saving multiple snapshots of each site over time will be [added eventually](https://github.com/ArchiveBox/ArchiveBox/issues/179) (along with the ability to view diffs of the changes between runs). For now ArchiveBox is designed to only archive each URL with each extractor type once. A workaround to take multiple snapshots of the same URL is to make them slightly different by adding a hash:

```bash
archivebox add 'https://example.com#2020-10-24'
...
archivebox add 'https://example.com#2020-10-25'
```

#### Storage Requirements

Because ArchiveBox is designed to ingest a firehose of browser history and bookmark feeds to a local disk, it can be much more disk-space intensive than a centralized service like the Internet Archive or Archive.today. However, as storage space gets cheaper and compression improves, you should be able to use it continuously over the years without having to delete anything.

ArchiveBox can use anywhere from ~1gb per 1000 articles, to ~50gb per 1000 articles, mostly dependent on whether you're saving audio & video using `SAVE_MEDIA=True` and whether you lower `MEDIA_MAX_SIZE=750mb`.

Storage requirements can be reduced by using a compressed/deduplicated filesystem like ZFS/BTRFS, or by turning off extractors methods you don't need. Don't store large collections on older filesystems like EXT3/FAT as they may not be able to handle more than 50k directory entries in the `archive/` folder.

Try to keep the `index.sqlite3` file on local drive (not a network mount), and ideally on an SSD for maximum performance, however the `archive/` folder can be on a network mount or spinning HDD.

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

The aim of ArchiveBox is to enable more of the internet to be archived by empowering people to self-host their own archives. The intent is for all the web content you care about to be viewable with common software in 50 - 100 years without needing to run ArchiveBox or other specialized software to replay it.

Vast treasure troves of knowledge are lost every day on the internet to link rot. As a society, we have an imperative to preserve some important parts of that treasure, just like we preserve our books, paintings, and music in physical libraries long after the originals go out of print or fade into obscurity.

Whether it's to resist censorship by saving articles before they get taken down or edited, or just to save a collection of early 2010's flash games you love to play, having the tools to archive internet content enables to you save the stuff you care most about before it disappears.

<div align="center">
<img src="https://i.imgur.com/bC6eZcV.png" width="40%"/><br/>
 <sup><i>Image from <a href="https://digiday.com/media/wtf-link-rot/">WTF is Link Rot?</a>...</i><br/></sup>
</div>

The balance between the permanence and ephemeral nature of content on the internet is part of what makes it beautiful. I don't think everything should be preserved in an automated fashion--making all content permanent and never removable, but I do think people should be able to decide for themselves and effectively archive specific content that they care about.

Because modern websites are complicated and often rely on dynamic content,
ArchiveBox archives the sites in **several different formats** beyond what public archiving services like Archive.org and Archive.is save. Using multiple methods and the market-dominant browser to execute JS ensures we can save even the most complex, finicky websites in at least a few high-quality, long-term data formats. All the archived links are stored by date bookmarked in `./archive/<timestamp>`, and everything is indexed nicely with SQLite3, JSON, and HTML files. 

## Comparison to Other Projects

<img src="https://i.imgur.com/4nkFjdv.png" width="5%" align="right" alt="comparison"/> 

▶ **Check out our [community page](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community) for an index of web archiving initiatives and projects.**

A variety of open and closed-source archiving projects exist, but few provide a nice UI and CLI to manage a large, high-fidelity archive collection over time.

ArchiveBox tries to be a robust, set-and-forget archiving solution suitable for archiving RSS feeds, bookmarks, or your entire browsing history (beware, it may be too big to store), ~~including private/authenticated content that you wouldn't otherwise share with a centralized service~~ (this is not recommended due to JS replay security concerns).

### Comparison With Centralized Public Archives

Not all content is suitable to be archived in a centralized collection, wehther because it's private, copyrighted, too large, or too complex. ArchiveBox hopes to fill that gap.

By having each user store their own content locally, we can save much larger portions of everyone's browsing history than a shared centralized service would be able to handle. The eventual goal is to work towards federated archiving where users can share portions of their collections with each other.

### Comparison With Other Self-Hosted Archiving Options

ArchiveBox differentiates itself from [similar self-hosted projects](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#Web-Archiving-Projects) by providing both a comprehensive CLI interface for managing your archive, a Web UI that can be used either indepenently or together with the CLI, and a simple on-disk data format that can be used without either.

ArchiveBox is neither the highest fidelity, nor the simplest tool available for self-hosted archiving, rather it's a jack-of-all-trades that tries to do most things well by default. It can be as simple or advanced as you want, and is designed to do everything out-of-the-box but be tuned to suit your needs.

*If being able to archive very complex interactive pages with JS and video is paramount, check out ArchiveWeb.page and ReplayWeb.page.*

*If you prefer a simpler, leaner solution that archives page text in markdown and provides note-taking abilities, check out Archivy or 22120.*

For more alternatives, see our [list here](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#Web-Archiving-Projects)...

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
- Reach out to me for questions and comments via [@ArchiveBoxApp](https://twitter.com/ArchiveBoxApp) or [@theSquashSH](https://twitter.com/thesquashSH) on Twitter
- Hire us to develop an internet archiving solution for you [@MonadicalSAS](https://twitter.com/MonadicalSAS) [Monadical.com](https://monadical.com)

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

<details><summary><i>Click to expand...</i></summary>

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
# or
archivebox setup

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
docker run -it archivebox init --setup
docker run -it -p 8000:8000 \
    -v $PWD/data:/data \
    -v $PWD/archivebox:/app/archivebox \
    archivebox server 0.0.0.0:8000 --debug --reload

# (remove the --reload flag and add the --nothreading flag when profiling with the django debug toolbar)
```

</details>

### Common development tasks

See the `./bin/` folder and read the source of the bash scripts within.
You can also run all these in Docker. For more examples see the Github Actions CI/CD tests that are run: `.github/workflows/*.yaml`.

#### Run in DEBUG mode

<details><summary><i>Click to expand...</i></summary>

```bash
archivebox config --set DEBUG=True
# or
archivebox server --debug ...
```

</details>

#### Build and run a Github branch

<details><summary><i>Click to expand...</i></summary>

```bash
docker build -t archivebox:dev https://github.com/ArchiveBox/ArchiveBox.git#dev
docker run -it -v $PWD:/data archivebox:dev ...
```

</details>

#### Run the linters

<details><summary><i>Click to expand...</i></summary>

```bash
./bin/lint.sh
```
(uses `flake8` and `mypy`)

</details>

#### Run the integration tests

<details><summary><i>Click to expand...</i></summary>

```bash
./bin/test.sh
```
(uses `pytest -s`)

</details>

#### Make migrations or enter a django shell

<details><summary><i>Click to expand...</i></summary>

Make sure to run this whenever you change things in `models.py`.
```bash
cd archivebox/
./manage.py makemigrations

cd path/to/test/data/
archivebox shell
archivebox manage dbshell
```
(uses `pytest -s`)

</details>

#### Build the docs, pip package, and docker image

<details><summary><i>Click to expand...</i></summary>

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

</details>

#### Roll a release

<details><summary><i>Click to expand...</i></summary>

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

</details>

---

## More ArchiveBox Resources

- Main site: https://archivebox.io (via Github Pages)
- Demo site: https://demo.archivebox.io (hosted by Monadical.com)
- Docs site: https://docs.archivebox.io (via ReadTheDocs.org)
- Docs wiki: https://wiki.archivebox.io (via Github Wiki)
- Issues: https://issues.archivebox.io (via Github Issues)
- Forum: https://forum.archivebox.io (via Github Discussions)
- Releases: https://releases.archivebox.io (via ReleasePage.co)
- Donations: https://github.com/sponsors/pirate

---

<div align="center">
<br/><br/>
<img src="https://raw.githubusercontent.com/Monadical-SAS/redux-time/HEAD/examples/static/jeremy.jpg" height="40px"/>
<br/>
<i><sub>
This project is maintained mostly in <a href="https://nicksweeting.com/blog#About">my spare time</a> with the help from generous contributors and Monadical (✨  <a href="https://monadical.com">hire them</a> for dev work!).
</sub>
</i>
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

[![](https://api.releasepage.co/v1/pages/23bfec45-7105-4fd1-9f87-806ae7ff56bb/badge.svg?apiKey=live.clBJeKsXJ6gsidbO)](http://releases.archivebox.io)

</div>
