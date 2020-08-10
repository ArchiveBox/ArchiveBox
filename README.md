<div align="center">
<img src="https://i.imgur.com/4nkFjdv.png" height="80px">
<h1>ArchiveBox<br/><sub>The open-source self-hosted web archive.</sub></h1>

▶️ <a href="https://github.com/pirate/ArchiveBox/wiki/Quickstart">Quickstart</a> | 
<a href="https://archivebox.zervice.io/">Demo</a> | 
<a href="https://github.com/pirate/ArchiveBox">Github</a> | 
<a href="https://github.com/pirate/ArchiveBox/wiki">Documentation</a> | 
<a href="#background--motivation">Info & Motivation</a> | 
<a href="https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community">Community</a> | 
<a href="https://github.com/pirate/ArchiveBox/wiki/Roadmap">Roadmap</a>

<pre>
"Your own personal internet archive" (网站存档 / 爬虫)
</pre>

<!--<a href="http://webchat.freenode.net?channels=ArchiveBox&uio=d4"><img src="https://img.shields.io/badge/Community_chat-IRC-%2328A745.svg"/></a>-->

<a href="https://github.com/pirate/ArchiveBox/blob/master/LICENSE"><img src="https://img.shields.io/badge/Open_source-MIT-green.svg?logo=git&logoColor=green"/></a>
<a href="https://github.com/pirate/ArchiveBox/commits/dev"><img src="https://img.shields.io/github/last-commit/pirate/ArchiveBox.svg?logo=Sublime+Text&logoColor=green&label=Active"/></a>
<a href="https://github.com/pirate/ArchiveBox"><img src="https://img.shields.io/github/stars/pirate/ArchiveBox.svg?logo=github&label=Stars&logoColor=blue"/></a>
<a href="https://test.pypi.org/project/archivebox/"><img src="https://img.shields.io/badge/Python-%3E%3D3.7-yellow.svg?logo=python&logoColor=yellow"/></a>
<a href="https://github.com/pirate/ArchiveBox/wiki/Install#dependencies"><img src="https://img.shields.io/badge/Chromium-%3E%3D59-orange.svg?logo=Google+Chrome&logoColor=orange"/></a>
<a href="https://hub.docker.com/r/nikisweeting/archivebox"><img src="https://img.shields.io/badge/Docker-all%20platforms-lightblue.svg?logo=docker&logoColor=lightblue"/></a>
<hr/>
</div>

**ArchiveBox takes a list of website URLs you want to archive, and creates a local, static, browsable HTML clone of the content from those websites (it saves HTML, JS, media files, PDFs, images and more).**

You can use it to preserve access to websites you care about by storing them locally offline. ArchiveBox imports lists of URLs, renders the pages in a headless, authenticated, user-scriptable browser, and then archives the content in multiple redundant common formats (HTML, PDF, PNG, WARC) that will last long after the originals disappear off the internet. It automatically extracts assets and media from pages and saves them in easily-accessible folders, with out-of-the-box support for extracting git repositories, audio, video, subtitles, images, PDFs, and more.

#### How does it work?

```bash
mkdir data && cd data
archivebox init
archivebox add 'https://example.com'
archivebox add 'https://getpocket.com/users/USERNAME/feed/all' --depth=1
archivebox server
```

After installing archivebox, just pass some new links to the `archivebox add` command to start your collection.

ArchiveBox is written in Python 3.7 and uses wget, Chrome headless, youtube-dl, pywb, and other common UNIX tools to save each page you add in multiple redundant formats. It doesn't require a constantly running server or backend (though it does include an optional one), just open the generated `data/index.html` in a browser to view the archive or run `archivebox server` to use the interactive Web UI. It can import and export links as JSON (among other formats), so it's easy to script or hook up to other APIs. If you run it on a schedule and import from browser history or bookmarks regularly, you can sleep soundly knowing that the slice of the internet you care about will be automatically preserved in multiple, durable long-term formats that will be accessible for decades (or longer).

<div align="center">

<img src="https://i.imgur.com/3tBL7PU.png" width="22%" alt="CLI Screenshot" align="top">
<img src="https://i.imgur.com/viklZNG.png" width="22%" alt="Desktop index screenshot" align="top">
<img src="https://i.imgur.com/RefWsXB.jpg" width="22%" alt="Desktop details page Screenshot"/>
<img src="https://i.imgur.com/M6HhzVx.png" width="22%" alt="Desktop details page Screenshot"/><br/>
<sup><a href="https://archive.sweeting.me/">Demo</a> | <a href="https://github.com/pirate/ArchiveBox/wiki/Usage">Usage</a> | <a href="#screenshots">Screenshots</a></sup>
<br/>
<sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub>
</div><br/>

## Quickstart

ArchiveBox is written in `python3.7` and has [3 main binary dependencies](https://github.com/pirate/ArchiveBox/wiki/Install#dependencies): `wget`, `chromium`, and `youtube-dl`.
To get started, you can [install them manually](https://github.com/pirate/ArchiveBox/wiki/Install) using your system's package manager, use the [automated helper script](https://github.com/pirate/ArchiveBox/wiki/Quickstart), or use the official [Docker](https://github.com/pirate/ArchiveBox/wiki/Docker) container. All three dependencies are optional if [disabled](https://github.com/pirate/ArchiveBox/wiki/Configuration#archive-method-toggles) in settings.

```bash
# Docker
mkdir data && cd data
docker run -v $PWD:/data nikisweeting/archivebox init
docker run -v $PWD:/data nikisweeting/archivebox add 'https://example.com'
docker run -v $PWD:/data -it nikisweeting/archivebox manage createsuperuser
docker run -v $PWD:/data -p 8000:8000 nikisweeting/archivebox server 0.0.0.0:8000
open http://127.0.0.1:8000
```

```bash
# Docker Compose
# first download: https://github.com/pirate/ArchiveBox/blob/master/docker-compose.yml
docker-compose run archivebox init
docker-compose run archivebox add 'https://example.com'
docker-compose run archivebox manage createsuperuser
docker-compose up
open http://127.0.0.1:8000
```

```bash
# Bare Metal
# Use apt on Ubuntu/Debian, brew on mac, or pkg on BSD
apt install python3 python3-pip git curl wget youtube-dl chromium-browser

pip install archivebox      # install archivebox

mkdir data && cd data       # (doesn't have to be called data)
archivebox init
archivebox add 'https://example.com'  # add URLs via args or stdin

# or import an RSS/JSON/XML/TXT feed/list of links
archivebox add https://getpocket.com/users/USERNAME/feed/all --depth=1
```

Once you've added your first links, open `data/index.html` in a browser to view the static archive.

You can also start it as a server with a full web UI to manage your links:
```bash
archivebox manage createsuperuser
archivebox server
```

You can visit `http://127.0.0.1:8000` in your browser to access it.

[DEMO: archivebox.zervice.io/](https://archivebox.zervice.io)  
For more information, see the [full Quickstart guide](https://github.com/pirate/ArchiveBox/wiki/Quickstart), [Usage](https://github.com/pirate/ArchiveBox/wiki/Usage), and [Configuration](https://github.com/pirate/ArchiveBox/wiki/Configuration) docs.

---

<div align="center">
<img src="https://i.imgur.com/PVO88AZ.png" width="80%"/>
</div>

# Overview

Because modern websites are complicated and often rely on dynamic content,
ArchiveBox archives the sites in **several different formats** beyond what public
archiving services like Archive.org and Archive.is are capable of saving. Using multiple
methods and the market-dominant browser to execute JS ensures we can save even the most
complex, finicky websites in at least a few high-quality, long-term data formats.

ArchiveBox imports a list of URLs from stdin, remote URL, or file, then adds the pages to a local archive folder using wget to create a browsable HTML clone, youtube-dl to extract media, and a full instance of Chrome headless for PDF, Screenshot, and DOM dumps, and more...

Running `archivebox add` adds only new, unique links into your collection on each run. Because it will ignore duplicates and only archive each link the first time you add it, you can schedule it to [run on a timer](https://github.com/pirate/ArchiveBox/wiki/Scheduled-Archiving) and re-import all your feeds multiple times a day. It will run quickly even if the feeds are large, because it's only archiving the newest links since the last run. For each link, it runs through all the archive methods. Methods that fail will save `None` and be automatically retried on the next run, methods that succeed save their output into the data folder and are never retried/overwritten by subsequent runs. Support for saving multiple snapshots of each site over time will be [added soon](https://github.com/pirate/ArchiveBox/issues/179) (along with the ability to view diffs of the changes between runs).

All the archived links are stored by date bookmarked in `./archive/<timestamp>`, and everything is indexed nicely with JSON & HTML files. The intent is for all the content to be viewable with common software in 50 - 100 years without needing to run ArchiveBox in a VM.

#### Can import links from many formats:

```bash
echo 'http://example.com' | archivebox add
archivebox add ~/Downloads/firefox_bookmarks_export.html --depth=1
archivebox add https://example.com/some/rss/feed.xml --depth=1
```

- <img src="https://nicksweeting.com/images/bookmarks.png" height="22px"/> Browser history or bookmarks exports (Chrome, Firefox, Safari, IE, Opera, and more)
- <img src="https://nicksweeting.com/images/rss.svg" height="22px"/> RSS, XML, JSON, CSV, SQL, HTML, Markdown, TXT, or any other text-based format
- <img src="https://getpocket.com/favicon.ico" height="22px"/> Pocket, Pinboard, Instapaper, Shaarli, Delicious, Reddit Saved Posts, Wallabag, Unmark.it, OneTab, and more

See the [Usage: CLI](https://github.com/pirate/ArchiveBox/wiki/Usage#CLI-Usage) page for documentation and examples.

#### Saves lots of useful stuff for each imported link:

```bash
 ls ./archive/<timestamp>/
```

- **Index:** `index.html` & `index.json` HTML and JSON index files containing metadata and details
- **Title:** `title` title of the site
- **Favicon:** `favicon.ico` favicon of the site
- **WGET Clone:** `example.com/page-name.html` wget clone of the site, with .html appended if not present
- **WARC:** `warc/<timestamp>.gz` gzipped WARC of all the resources fetched while archiving
- **PDF:** `output.pdf` Printed PDF of site using headless chrome
- **Screenshot:** `screenshot.png` 1440x900 screenshot of site using headless chrome
- **DOM Dump:** `output.html` DOM Dump of the HTML after rendering using headless chrome
- **URL to Archive.org:** `archive.org.txt` A link to the saved site on archive.org
- **Audio & Video:** `media/` all audio/video files + playlists, including subtitles & metadata with youtube-dl
- **Source Code:** `git/` clone of any repository found on github, bitbucket, or gitlab links
- _More coming soon! See the [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap)..._

It does everything out-of-the-box by default, but you can disable or tweak [individual archive methods](https://github.com/pirate/ArchiveBox/wiki/Configuration) via environment variables or config file.

If you're importing URLs with secret tokens in them (e.g Google Docs, CodiMD notepads, etc), you may want to disable some of these methods to avoid leaking private URLs to 3rd party APIs during the archiving process. See the [Security Overview](https://github.com/pirate/ArchiveBox/wiki/Security-Overview#stealth-mode) page for more details.

## Key Features

- [**Free & open source**](https://github.com/pirate/ArchiveBox/blob/master/LICENSE), doesn't require signing up for anything, stores all data locally
- [**Few dependencies**](https://github.com/pirate/ArchiveBox/wiki/Install#dependencies) and [simple command line interface](https://github.com/pirate/ArchiveBox/wiki/Usage#CLI-Usage)
- [**Comprehensive documentation**](https://github.com/pirate/ArchiveBox/wiki), [active development](https://github.com/pirate/ArchiveBox/wiki/Roadmap), and [rich community](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community)
- **Doesn't require a constantly-running server**, proxy, or native app
- Easy to set up **[scheduled importing](https://github.com/pirate/ArchiveBox/wiki/Scheduled-Archiving) from multiple sources**
- Uses common, **durable, [long-term formats](#saves-lots-of-useful-stuff-for-each-imported-link)** like HTML, JSON, PDF, PNG, and WARC
- ~~**Suitable for paywalled / [authenticated content](https://github.com/pirate/ArchiveBox/wiki/Configuration#chrome_user_data_dir)** (can use your cookies)~~ (do not do this until v0.5 is released with some security fixes)
- Can [**run scripts during archiving**](https://github.com/pirate/ArchiveBox/issues/51) to [scroll pages](https://github.com/pirate/ArchiveBox/issues/80), [close modals](https://github.com/pirate/ArchiveBox/issues/175), expand comment threads, etc.
- Can also [**mirror content to 3rd-party archiving services**](https://github.com/pirate/ArchiveBox/wiki/Configuration#submit_archive_dot_org) automatically for redundancy

## Background & Motivation

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

## Comparison to Other Projects

▶ **Check out our [community page](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community) for an index of web archiving initiatives and projects.**

<img src="https://i.imgur.com/4nkFjdv.png" width="10%" align="left"/> The aim of ArchiveBox is to go beyond what the Wayback Machine and other public archiving services can do, by adding a headless browser to replay sessions accurately, and by automatically extracting all the content in multiple redundant formats that will survive being passed down to historians and archivists through many generations.

#### User Interface & Intended Purpose

ArchiveBox differentiates itself from [similar projects](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#Web-Archiving-Projects) by being a simple, one-shot CLI interface for users to ingest bulk feeds of URLs over extended periods, as opposed to being a backend service that ingests individual, manually-submitted URLs from a web UI. However, we also have the option to add urls via a web interface through our Django frontend.

#### Private Local Archives vs Centralized Public Archives

Unlike crawler software that starts from a seed URL and works outwards, or public tools like Archive.org designed for users to manually submit links from the public internet, ArchiveBox tries to be a set-and-forget archiver suitable for archiving your entire browsing history, RSS feeds, or bookmarks, ~~including private/authenticated content that you wouldn't otherwise share with a centralized service~~ (do not do this until v0.5 is released with some security fixes). Also by having each user store their own content locally, we can save much larger portions of everyone's browsing history than a shared centralized service would be able to handle.

#### Storage Requirements

Because ArchiveBox is designed to ingest a firehose of browser history and bookmark feeds to a local disk, it can be much more disk-space intensive than a centralized service like the Internet Archive or Archive.today. However, as storage space gets cheaper and compression improves, you should be able to use it continuously over the years without having to delete anything. In my experience, ArchiveBox uses about 5gb per 1000 articles, but your milage may vary depending on which options you have enabled and what types of sites you're archiving. By default, it archives everything in as many formats as possible, meaning it takes more space than a using a single method, but more content is accurately replayable over extended periods of time. Storage requirements can be reduced by using a compressed/deduplicated filesystem like ZFS/BTRFS, or by setting `SAVE_MEDIA=False` to skip audio & video files.

## Learn more

<!--▶ **Join out our [community chat](http://webchat.freenode.net?channels=ArchiveBox&uio=d4) hosted on IRC freenode.net:`#ArchiveBox`!**-->

Whether you want to learn which organizations are the big players in the web archiving space, want to find a specific open-source tool for your web archiving need, or just want to see where archivists hang out online, our Community Wiki page serves as an index of the broader web archiving community. Check it out to learn about some of the coolest web archiving projects and communities on the web!

<img src="https://i.imgur.com/0ZOmOvN.png" width="14%" align="right"/>

- [Community Wiki](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community)
  - [The Master Lists](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#The-Master-Lists)  
    _Community-maintained indexes of archiving tools and institutions._
  - [Web Archiving Software](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#Web-Archiving-Projects)  
    _Open source tools and projects in the internet archiving space._
  - [Reading List](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#Reading-List)  
    _Articles, posts, and blogs relevant to ArchiveBox and web archiving in general._
  - [Communities](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#Communities)  
    _A collection of the most active internet archiving communities and initiatives._
- Check out the ArchiveBox [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap) and [Changelog](https://github.com/pirate/ArchiveBox/wiki/Changelog)
- Learn why archiving the internet is important by reading the "[On the Importance of Web Archiving](https://parameters.ssrc.org/2018/09/on-the-importance-of-web-archiving/)" blog post.
- Or reach out to me for questions and comments via [@theSquashSH](https://twitter.com/thesquashSH) on Twitter.

---

# Documentation

<img src="https://read-the-docs-guidelines.readthedocs-hosted.com/_images/logo-dark.png" width="13%" align="right"/>

We use the [Github wiki system](https://github.com/pirate/ArchiveBox/wiki) and [Read the Docs](https://archivebox.readthedocs.io/en/latest/) for documentation.

You can also access the docs locally by looking in the [`ArchiveBox/docs/`](https://github.com/pirate/ArchiveBox/wiki/Home) folder.

You can build the docs by running:

```python
cd ArchiveBox
pipenv install --dev
sphinx-apidoc -o docs archivebox
cd docs/
make html
# then open docs/_build/html/index.html
```

## Getting Started

- [Quickstart](https://github.com/pirate/ArchiveBox/wiki/Quickstart)
- [Install](https://github.com/pirate/ArchiveBox/wiki/Install)
- [Docker](https://github.com/pirate/ArchiveBox/wiki/Docker)

## Reference

- [Usage](https://github.com/pirate/ArchiveBox/wiki/Usage)
- [Configuration](https://github.com/pirate/ArchiveBox/wiki/Configuration)
- [Supported Sources](https://github.com/pirate/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive)
- [Supported Outputs](https://github.com/pirate/ArchiveBox/wiki#can-save-these-things-for-each-site)
- [Scheduled Archiving](https://github.com/pirate/ArchiveBox/wiki/Scheduled-Archiving)
- [Publishing Your Archive](https://github.com/pirate/ArchiveBox/wiki/Publishing-Your-Archive)
- [Chromium Install](https://github.com/pirate/ArchiveBox/wiki/Install-Chromium)
- [Security Overview](https://github.com/pirate/ArchiveBox/wiki/Security-Overview)
- [Troubleshooting](https://github.com/pirate/ArchiveBox/wiki/Troubleshooting)

## More Info

- [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap)
- [Changelog](https://github.com/pirate/ArchiveBox/wiki/Changelog)
- [Donations](https://github.com/pirate/ArchiveBox/wiki/Donations)
- [Background & Motivation](https://github.com/pirate/ArchiveBox#background--motivation)
- [Web Archiving Community](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community)

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

<a href="https://twitter.com/thesquashSH"><img src="https://img.shields.io/badge/Tweet-%40theSquashSH-blue.svg?style=flat"/></a>
<a href="https://github.com/pirate/ArchiveBox"><img src="https://img.shields.io/github/stars/pirate/ArchiveBox.svg?style=flat&label=Star+on+Github"/></a>

<br/><br/>

</div>
