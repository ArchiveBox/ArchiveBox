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

You can use it to preserve access to websites you care about by storing them locally offline.  ArchiveBox works by rendering the pages in a headless browser, then saving all the requests and fully loaded pages in multiple redundant common formats (HTML, PDF, PNG, WARC) that will last long after the original content dissapears off the internet.  It also automatically extracts assets like git repositories, audio, video, subtitles, images, and PDFs into separate files using `youtube-dl`, `pywb`, and `wget`.

ArchiveBox doesn't require a constantly running server or backend, instead you just run the `./archive` command each time you want to import new links and update the static output.  It can import and export JSON (among other formats), so it's easy to script or hook up to other APIs.  If you run it on a schedule and import from browser history or bookmarks regularly, you can sleep soundly knowing that the slice of the internet you care about will be automatically preserved in multiple, durable long-term formats that will be accessible for decades (or longer).

<div align="center"><sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub></div><br/>


To get started, you can install ArchiveBox [automatically](https://github.com/pirate/ArchiveBox/wiki/Quickstart), follow the [manual instructions](https://github.com/pirate/ArchiveBox/wiki/Install), or use [Docker](https://github.com/pirate/ArchiveBox/wiki/Docker).  
There are only [3 main dependencies](https://github.com/pirate/ArchiveBox/wiki/Install#dependencies) beyond `python3`: `wget`, `chromium`, and `youtube-dl`, and you can skip installing them if you don't need those archive methods.
```bash
git clone https://github.com/pirate/ArchiveBox.git
cd ArchiveBox
./setup

# Export your bookmarks, then run the archive command to start archiving!
./archive ~/Downloads/bookmarks.html

# Or pass in links to archive via stdin
echo 'https://example.com' | ./archive
```

Open `output/index.html` in a browser to view your archive.  [DEMO: archive.sweeting.me](https://archive.sweeting.me)  
For more information, see the [Quickstart](https://github.com/pirate/ArchiveBox/wiki/Quickstart), [Usage](https://github.com/pirate/ArchiveBox/wiki/Usage), and [Configuration](https://github.com/pirate/ArchiveBox/wiki/Configuration) docs.

## Overview

Because modern websites are complicated and often rely on dynamic content, 
ArchiveBox archives the sites in **several different formats** beyond what public 
archiving services like Archive.org and Archive.is are capable of saving.

ArchiveBox imports a list of URLs from stdin, remote url, or file, then adds the pages to a local archive folder using wget to create a browsable html clone, youtube-dl to extract media, and a full instance of Chrome headless for PDF, Screenshot, and DOM dumps, and more...

Using multiple methods and the market-dominant browser to execute JS ensures we can save even the most complex, finicky websites in at least a few high-quality, long-term data formats.

### Can import links from:

 - <img src="https://getpocket.com/favicon.ico" height="22px"/> Pocket, Pinboard, Instapaper
 - <img src="https://nicksweeting.com/images/rss.svg" height="22px"/> RSS, XML, JSON, HTML, Markdown, or plain text lists
 - <img src="https://nicksweeting.com/images/bookmarks.png" height="22px"/> Browser history or bookmarks (Chrome, Firefox, Safari, IE, Opera, and more)
 - *Shaarli, Delicious, Reddit Saved Posts, Wallabag, Unmark.it, and any other text with links in it!*

### Can save these things for each site:

 - `favicon.ico` favicon of the site
 - `example.com/page-name.html` wget clone of the site, with .html appended if not present
 - `output.pdf` Printed PDF of site using headless chrome
 - `screenshot.png` 1440x900 screenshot of site using headless chrome
 - `output.html` DOM Dump of the HTML after rendering using headless chrome
 - `archive.org.txt` A link to the saved site on archive.org
 - `warc/` for the html + gzipped warc file <timestamp>.gz
 - `media/` any mp4, mp3, subtitles, and metadata found using youtube-dl
 - `git/` clone of any repository for github, bitbucket, or gitlab links
 - `index.html` & `index.json` HTML and JSON index files containing metadata and details

By default it does everything, but can disable or tweak [individual options](https://github.com/pirate/ArchiveBox/wiki/Configuration) via environment variables or config file.

The archiving is additive, so you can schedule `./archive` to [run regularly](https://github.com/pirate/ArchiveBox/wiki/Scheduled-Archiving) and pull new links into the index.
All the saved content is static and indexed with JSON files, so it lives forever & is easily parseable, it requires no always-running backend.

### Related Projects

There are tons of great web archiving tools out there.  In particular https://webrecorder.io ([pywb](https://github.com/webrecorder/pywb)) and https://getpolarized.io/ are robust, stable pieces of software that have lots of overlap with ArchiveBox.  ArchiveBox differentiates itself by being primarily a one-shot CLI tool that specializing in importing streams of links from RSS, JSON (good for automatically archiving from a stream of browser history or bookmarks on a schedule), as opposed to a desktop application or web service that requires human interaction to add links.

To learn more about the motivation for this project and how it fits into the broader community, see our [Web Archiving Community](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community) wiki page.

# Documentation


<div align="center">
<img src="https://i.imgur.com/PVO88AZ.png"/>
<br/>
    <sub><i>(Recently <a href="https://github.com/pirate/ArchiveBox/issues/108">renamed</a> from <code>Bookmark Archiver</code>)</i></sub>
</div>

---

We use the [Github wiki system](https://github.com/pirate/ArchiveBox/wiki) for documentation.

You can also access the docs locally by looking in the [`ArchiveBox/docs/`](https://github.com/pirate/ArchiveBox/wiki/Home) folder.

# Getting Started

 - [Home](https://github.com/pirate/ArchiveBox/wiki/Home)
 - [Quickstart](https://github.com/pirate/ArchiveBox/wiki/Quickstart)
 - [Install](https://github.com/pirate/ArchiveBox/wiki/Install)
 - [Docker](https://github.com/pirate/ArchiveBox/wiki/Docker)

# Documentation

 - [Usage](https://github.com/pirate/ArchiveBox/wiki/Usage)
 - [Configuration](https://github.com/pirate/ArchiveBox/wiki/Configuration)
 - [Supported Sources](https://github.com/pirate/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive)
 - [Supported Outputs](https://github.com/pirate/ArchiveBox/wiki#can-save-these-things-for-each-site)
 - [Scheduled Archiving](https://github.com/pirate/ArchiveBox/wiki/Scheduled-Archiving)
 - [Publishing Your Archive](https://github.com/pirate/ArchiveBox/wiki/Publishing-Your-Archive)
 - [Chromium Install](https://github.com/pirate/ArchiveBox/wiki/Install-Chromium)
 - [Troubleshooting](https://github.com/pirate/ArchiveBox/wiki/Troubleshooting)

# More Info

 - [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap)
 - [Changelog](https://github.com/pirate/ArchiveBox/wiki/Changelog)
 - [Donations](https://github.com/pirate/ArchiveBox/wiki/Donations)
 - [Web Archiving Community](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community)


# Background & Motivation

Vast treasure troves of knowledge are lost every day on the internet to link rot.  As a society, we have an imperative
to preserve some important parts of that treasure, just like we preserve our books, paintings, and music in physical libraries long after the originals go out of print or fade into obscurity.

Whether it's to resist censorship by saving articles before they get taken down or editied, or
just to save a collection of early 2010's flash games you love to play, having the tools to 
archive internet content enables to you save the stuff you care most about before it dissapears.

The balance between the permanence and ephemeral nature of content on the internet is part of what makes it beautiful. 
I don't think everything should be preserved in an automated fashion, making all content permanent and never removable, but I do think people should be able to decide for themselves and effectively archive specific content that they care about.

The aim of ArchiveBox is to go beyond what the Wayback Machine and other public archiving services can do, by adding a headless browser to replay sessions accurately, and by automatically extracting all the content in multiple redundant formats that will survive being passed down to historians and archivists through many generations.

*Read more:*

- Learn why archiving the internet is important by reading the "[On the Importance of Web Archiving](https://parameters.ssrc.org/2018/09/on-the-importance-of-web-archiving/)" blog post.
- Discover the web archiving community on the [community](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community) wiki page.
- Find other archving projects on Github using the [awesome-web-archiving](https://github.com/iipc/awesome-web-archiving) list.
- Or reach out to me for questions and comments via [@theSquashSH](https://twitter.com/thesquashSH) on Twitter.

To learn more about ArchiveBox's past history and future plans, check out the [roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap) and [changelog](https://github.com/pirate/ArchiveBox/wiki/Changelog).

# Screenshots

<img src="https://i.imgur.com/viklZNG.png" width="75%" alt="Desktop index screenshot" align="top"><img src="https://i.imgur.com/mW2dITg.png" width="25%" alt="Mobile details page screenshot" align="top"><br/>
<img src="https://i.imgur.com/wnpdAVM.jpg" width="100%" alt="Desktop details page Screenshot"/><br/>
<img src="https://i.imgur.com/3tBL7PU.png" width="100%" alt="CLI Screenshot">

---

<div align="center">
<br/><br/>
<img src="https://raw.githubusercontent.com/Monadical-SAS/redux-time/HEAD/examples/static/jeremy.jpg" height="40px"/>
<br/>
<sub><i>This project is maintained mostly in my spare time with the help from generous contributors.</i></sub>
<br/><br/>
<a href="https://www.patreon.com/theSquashSH"><img src="https://img.shields.io/badge/Donate_to_support_development-via_Patreon-%23DD5D76.svg?style=flat"/></a>
<br/>
<br/>
<a href="https://twitter.com/thesquashSH"><img src="https://img.shields.io/badge/Tweet-%40theSquashSH-blue.svg?style=flat"/></a>
<a href="https://github.com/pirate/ArchiveBox"><img src="https://img.shields.io/github/stars/pirate/ArchiveBox.svg?style=flat&label=Star+on+Github"/></a>
</div>
