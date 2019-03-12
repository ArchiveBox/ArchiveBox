<div align="center">
<img src="https://i.imgur.com/4nkFjdv.png" height="80px">
<h1>ArchiveBox<br/><sub>The open-source self-hosted web archive.</sub></h1>

▶️ <a href="https://github.com/pirate/ArchiveBox/wiki/Quickstart">Quickstart</a> | 
<a href="https://archive.sweeting.me">Demo</a> | 
<a href="https://archivebox.io">Website</a> | 
<a href="https://github.com/pirate/ArchiveBox">Github</a> | 
<a href="https://github.com/pirate/ArchiveBox/wiki">Documentation</a> | 
<a href="https://github.com/pirate/ArchiveBox/wiki/Troubleshooting">Troubleshooting</a> | 
<a href="https://github.com/pirate/ArchiveBox/wiki/Changelog">Changelog</a> | 
<a href="https://github.com/pirate/ArchiveBox/wiki/Roadmap">Roadmap</a>

<pre>
"Your own personal internet archive" (网站存档 / 爬虫)
</pre>

<a href="https://github.com/pirate/ArchiveBox">
<img src="https://img.shields.io/badge/Open_source-free-green.svg?logo=git&logoColor=green"/>
<img src="https://img.shields.io/github/last-commit/pirate/ArchiveBox.svg?logo=Sublime+Text&logoColor=green&label=Active"/>
<img src="https://img.shields.io/badge/License-MIT-lightgreen.svg?logo=MakerBot&logoColor=lightgreen"/>
<img src="https://img.shields.io/github/stars/pirate/ArchiveBox.svg?logo=github&label=Stars&logoColor=blue"/>
<img src="https://img.shields.io/badge/Python-%3E%3D3.5-yellow.svg?logo=python&logoColor=yellow"/>
<img src="https://img.shields.io/badge/Chromium-%3E%3D59-orange.svg?logo=Google+Chrome&logoColor=orange"/>
<img src="https://img.shields.io/badge/Docker-all%20platforms-lightblue.svg?logo=docker&logoColor=lightblue"/>
</a>
<hr/>
</div>

**ArchiveBox takes a list of website URLs you want to archive, and creates a local, static, browsable HTML clone of the content from those websites (it saves HTML, JS, media files, PDFs, images and more).** 

You can use it to preserve access to websites you care about by storing them locally offline.  ArchiveBox works by rendering the pages in a headless browser, then saving all the requests and fully loaded pages in multiple redundant common formats (HTML, PDF, PNG, WARC) that will last long after the original content disappears off the internet.  It also automatically extracts assets like git repositories, audio, video, subtitles, images, and PDFs into separate files using `youtube-dl`, `pywb`, and `wget`.

#### How does it work?

Simply download this repo, and run the `./archive` command each time you want to import new links and update your local archive. ArchiveBox is written in Python 3 and uses wget, Chrome headless, youtube-dl, pywb, and other common unix tools to save each page you add in multiple redundant formats. 

It doesn't require a constantly running server or backend, just run the command and open the outputted static HTML in a browser to view the archive. It can import and export JSON (among other formats), so it's easy to script or hook up to other APIs.  If you run it on a schedule and import from browser history or bookmarks regularly, you can sleep soundly knowing that the slice of the internet you care about will be automatically preserved in multiple, durable long-term formats that will be accessible for decades (or longer).

<div align="center">
<a href="#screenshots">
<img src="https://i.imgur.com/3tBL7PU.png" width="30%" alt="CLI Screenshot" align="top">
<img src="https://i.imgur.com/viklZNG.png" width="30%" alt="Desktop index screenshot" align="top">
<img src="https://i.imgur.com/RefWsXB.jpg" width="30%" alt="Desktop details page Screenshot"/>
</a><br/>
<sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub>
</div><br/>

## Quickstart

ArchiveBox has [3 main dependencies](https://github.com/pirate/ArchiveBox/wiki/Install#dependencies) beyond `python3`: `wget`, `chromium`, and `youtube-dl`.
To get started, you can [install them manually](https://github.com/pirate/ArchiveBox/wiki/Install) using your system's package manager, you can use the [automated helper script](https://github.com/pirate/ArchiveBox/wiki/Quickstart), or you can use the official [Docker](https://github.com/pirate/ArchiveBox/wiki/Docker) container.  All three dependencies are optional if [disabled](https://github.com/pirate/ArchiveBox/wiki/Configuration#archive-method-toggles) in settings.

```bash
# 1. Install dependencies (use apt on ubuntu, brew on mac, or pkg on BSD)
apt install python3 python3-pip git curl wget youtube-dl chromium-browser

# 2. Download ArchiveBox
git clone https://github.com/pirate/ArchiveBox.git && cd ArchiveBox

# 3. Add your first links to your archive
echo 'https://example.com' | ./archive                  # pass URLs to archive via stdin

./archive https://getpocket.com/users/example/feed/all  # or import an RSS/JSON/XML/TXT feed
```

One you've added your first links, open `output/index.html` in a browser to view the archive.  [DEMO: archive.sweeting.me](https://archive.sweeting.me)  
For more information, see the [full Quickstart guide](https://github.com/pirate/ArchiveBox/wiki/Quickstart), [Usage](https://github.com/pirate/ArchiveBox/wiki/Usage), and [Configuration](https://github.com/pirate/ArchiveBox/wiki/Configuration) docs.  

*(`pip install archivebox` will be available in the near future, follow our [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap) for progress)*

<div align="center"><sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub></div><br/>

## Overview

Because modern websites are complicated and often rely on dynamic content, 
ArchiveBox archives the sites in **several different formats** beyond what public 
archiving services like Archive.org and Archive.is are capable of saving.

ArchiveBox imports a list of URLs from stdin, remote URL, or file, then adds the pages to a local archive folder using wget to create a browsable HTML clone, youtube-dl to extract media, and a full instance of Chrome headless for PDF, Screenshot, and DOM dumps, and more...

Using multiple methods and the market-dominant browser to execute JS ensures we can save even the most complex, finicky websites in at least a few high-quality, long-term data formats.

### Can import links from:

 - <img src="https://getpocket.com/favicon.ico" height="22px"/> Pocket, Pinboard, Instapaper
 - <img src="https://nicksweeting.com/images/rss.svg" height="22px"/> RSS, XML, JSON, HTML, Markdown, or plain text lists
 - <img src="https://nicksweeting.com/images/bookmarks.png" height="22px"/> Browser history or bookmarks (Chrome, Firefox, Safari, IE, Opera, and more)
 - *Shaarli, Delicious, Reddit Saved Posts, Wallabag, Unmark.it, and any other text with links in it!*

### Can save these things for each site:

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
 - *More coming soon! See the [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap)...*

By default it does everything but you can disable or tweak [individual options](https://github.com/pirate/ArchiveBox/wiki/Configuration) via environment variables or config file.

The archiving is additive so you can schedule `./archive` to [run regularly](https://github.com/pirate/ArchiveBox/wiki/Scheduled-Archiving) and pull new links into the index.
All the saved content is static and indexed with JSON files, so it lives forever & is easily parseable, it requires no always-running backend.

## Background & Motivation

Vast treasure troves of knowledge are lost every day on the internet to link rot.  As a society, we have an imperative to preserve some important parts of that treasure, just like we preserve our books, paintings, and music in physical libraries long after the originals go out of print or fade into obscurity.

Whether it's to resist censorship by saving articles before they get taken down or edited, or
just to save a collection of early 2010's flash games you love to play, having the tools to 
archive internet content enables to you save the stuff you care most about before it disappears.

<div align="center">
<img src="https://i.imgur.com/bC6eZcV.png" width="50%"/><br/>
 <sup><i>Image from <a href="https://digiday.com/media/wtf-link-rot/">WTF is Link Rot?</a>...</i><br/></sup>
</div>

The balance between the permanence and ephemeral nature of content on the internet is part of what makes it beautiful. 
I don't think everything should be preserved in an automated fashion, making all content permanent and never removable, but I do think people should be able to decide for themselves and effectively archive specific content that they care about.


### Comparison to other Projects

<img src="https://i.imgur.com/4nkFjdv.png" width="10%" align="left"/> The aim of ArchiveBox is to go beyond what the Wayback Machine and other public archiving services can do, by adding a headless browser to replay sessions accurately, and by automatically extracting all the content in multiple redundant formats that will survive being passed down to historians and archivists through many generations.

ArchiveBox differentiates itself from [similar projects](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#Web-Archiving-Projects) by trying to be a simple, robust, way for the average tech-savvy user to save sizable portions of the content they view and care about locally.  Unlike crawler software that starts from a seed URL and works outwards, or public tools like Archive.org designed for users to manually submit links from the public internet, ArchiveBox tries to be a set-and-forget archiver suitable for archiving your browsing history, RSS feeds, or bookmarks, including private/authenticated content that you wouldn't want to share with a centralized service.

### Read more

Whether you want learn which organizations are the big players in the web archiving space, want to find a specific open source tool for your web archiving need, or just want to see where archivists hang out online, our Community Wiki page serves as an index of the broader web archiving community.  Check it out to learn about some of the coolest web archiving projects and communities on the web!

<img src="https://i.imgur.com/0ZOmOvN.png" width="14%" align="right"/>

 - [Community Wiki](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community)
   + [The Master Lists](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#The-Master-Lists)  
     *Community-maintained indexes of archiving tools and institutions.* 
   + [Web Archiving Software](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#Web-Archiving-Projects)  
     *Open source tools and projects in the internet archiving space.*
   + [Reading List](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#Reading-List)  
     *Articles, posts, and blogs relevant to ArchiveBox and web archiving in general.*
   + [Communities](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community#Communities)  
     *A collection of the most active internet archiving communities and initiatives.*
 - Check out the ArchiveBox [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap) and [Changelog](https://github.com/pirate/ArchiveBox/wiki/Changelog)
 - Learn why archiving the internet is important by reading the "[On the Importance of Web Archiving](https://parameters.ssrc.org/2018/09/on-the-importance-of-web-archiving/)" blog post.
 - Or reach out to me for questions and comments via [@theSquashSH](https://twitter.com/thesquashSH) on Twitter.
 
<div align="center"><sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub></div><br/>
 
# Documentation

<img src="https://read-the-docs-guidelines.readthedocs-hosted.com/_images/logo-dark.png" width="13%" align="right"/>

We use the [Github wiki system](https://github.com/pirate/ArchiveBox/wiki) for documentation.

You can also access the docs locally by looking in the [`ArchiveBox/docs/`](https://github.com/pirate/ArchiveBox/wiki/Home) folder.

## Getting Started

 - [Home](https://github.com/pirate/ArchiveBox/wiki/Home)
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
 - [Troubleshooting](https://github.com/pirate/ArchiveBox/wiki/Troubleshooting)

## More Info

 - [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap)
 - [Changelog](https://github.com/pirate/ArchiveBox/wiki/Changelog)
 - [Donations](https://github.com/pirate/ArchiveBox/wiki/Donations)
 - [Web Archiving Community](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community)

---

<div align="center">
<img src="https://i.imgur.com/PVO88AZ.png" width="80%"/>
</div>


# Screenshots

<img src="https://i.imgur.com/viklZNG.png" width="75%" alt="Desktop index screenshot" align="top"><img src="https://i.imgur.com/mW2dITg.png" width="25%" alt="Mobile details page screenshot" align="top"><br/>
<img src="https://i.imgur.com/wnpdAVM.jpg" width="100%" alt="Desktop details page Screenshot"/><br/>
<img src="https://i.imgur.com/3tBL7PU.png" width="100%" alt="CLI Screenshot">

---

<div align="center">
<br/><br/>
<img src="https://raw.githubusercontent.com/Monadical-SAS/redux-time/HEAD/examples/static/jeremy.jpg" height="40px"/>
<br/>
<sub><i>This project is maintained mostly in <a href="https://nicksweeting.com/blog#About">my spare time</a> with the help from generous contributors.</i></sub>
<br/><br/>
Contributor Spotlight:<br/><br/>
 
[![](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/images/0)](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/links/0)[![](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/images/1)](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/links/1)[![](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/images/2)](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/links/2)[![](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/images/3)](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/links/3)[![](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/images/4)](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/links/4)[![](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/images/5)](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/links/5)[![](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/images/6)](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/links/6)[![](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/images/7)](https://sourcerer.io/fame/pirate/pirate/ArchiveBox/links/7)

<br/>
<a href="https://www.patreon.com/theSquashSH"><img src="https://img.shields.io/badge/Donate_to_support_development-via_Patreon-%23DD5D76.svg?style=flat"/></a>
<br/>
<br/>
<a href="https://twitter.com/thesquashSH"><img src="https://img.shields.io/badge/Tweet-%40theSquashSH-blue.svg?style=flat"/></a>
<a href="https://github.com/pirate/ArchiveBox"><img src="https://img.shields.io/github/stars/pirate/ArchiveBox.svg?style=flat&label=Star+on+Github"/></a>

<br/><br/>

</div>
