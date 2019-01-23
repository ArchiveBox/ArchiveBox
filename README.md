<div align="center">

# ArchiveBox <br/> <sub><img src="https://nicksweeting.com/images/archive.png" height="20px"/> The open-source self-hosted web archive <img src="https://nicksweeting.com/images/archive.png" height="20px"/></sub>

[![Activity](https://img.shields.io/github/last-commit/pirate/ArchiveBox.svg) ![Github](https://img.shields.io/badge/Open_source-Free-green.svg?logo=github) ![License](https://img.shields.io/github/license/pirate/ArchiveBox.svg) ![Github Stars](https://img.shields.io/github/stars/pirate/ArchiveBox.svg) ![Language](https://img.shields.io/badge/python-3.5%20%7C%203.6%20%7C%203.7-yellow.svg) ![Chromium](https://img.shields.io/badge/chromium-%3E%3D65-silver.svg) ![Docker](https://img.shields.io/badge/docker-all%20platforms-silver.svg?logo=docker)](https://github.com/pirate/ArchiveBox)

    "Your own personal Way-Back Machine" (网站存档 / 爬虫)

▶️ [Quickstart](https://github.com/pirate/ArchiveBox/wiki/Quickstart) | [Details](https://github.com/pirate/ArchiveBox/wiki) | [Configuration](https://github.com/pirate/ArchiveBox/wiki/Configuration) | [Troubleshooting](https://github.com/pirate/ArchiveBox/wiki/Troubleshooting) | [Demo](https://archive.sweeting.me) | [Website](https://archivebox.io/) | [Github](https://github.com/pirate/ArchiveBox/) | [Changelog](https://github.com/pirate/ArchiveBox/wiki/Changelog) | [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap)

---

</div>

**ArchiveBox archives a copy of websites you choose into a local static HTML folder.**  
You can use it to archive and browse content you care about long after it's deleted or moved off the internet.

Because modern websites are complicated and often rely on dynamic content, 
*ArchiveBox saves the sites in a number of formats* beyond what sites sites like
Archive.org and Archive.is are capable of saving.  ArchiveBox uses wget to save the 
html, youtube-dl for media, and a full instance of Chrome headless for PDF, Screenshot,
and DOM dumps to greatly improve redundancy.  Using multiple methods in conjunction 
with the most popular browser on the market ensures we can execute almost all the JS
out there, and archive even the most difficult sites in at least one format.

If you run it on a schedule to import your history or bookmarks continusously, you can rest soundly knowing that
the slice of the internet you care about can be preserved long after the servers go down or the links break.

### Can import links from:

 - <img src="https://nicksweeting.com/images/bookmarks.png" height="22px"/> Browser history or bookmarks (Chrome, Firefox, Safari, IE, Opera)
 - <img src="https://nicksweeting.com/images/rss.svg" height="22px"/> RSS or plain text lists
 - <img src="https://getpocket.com/favicon.ico" height="22px"/> <img src="https://pinboard.in/favicon.ico" height="22px"/> Pocket, Pinboard, Instapaper
 - *Shaarli, Delicious, Reddit Saved Posts, Wallabag, Unmark.it, and any other text with links in it!*

### Can save these things for each site:

 - `example.com/page-name.html` wget clone of the site, with .html appended if not present
 - `output.pdf` Printed PDF of site using headless chrome
 - `screenshot.png` 1440x900 screenshot of site using headless chrome
 - `output.html` DOM Dump of the HTML after rendering using headless chrome
 - `archive.org.txt` A link to the saved site on archive.org
 - `warc/` for the html + gzipped warc file <timestamp>.gz
 - `media/` any mp4, mp3, subtitles, and metadata found using youtube-dl
 - `git/` clone of any repository for github, bitbucket, or gitlab links
 - `favicon.ico` favicon of the site
 - `index.json` JSON index containing link info and archive details
 - `index.html` HTML index containing link info and archive details (optional fancy or simple index)

The archiving is additive, so you can schedule `./archive` to run regularly and pull new links into the index.
All the saved content is static and indexed with JSON files, so it lives forever & is easily parseable, it requires no always-running backend.

[DEMO: archive.sweeting.me](https://archive.sweeting.me)

To get started, you can install [automatically](https://github.com/pirate/ArchiveBox/wiki/Quickstart), follow the [manual instructions](https://github.com/pirate/ArchiveBox/wiki/Install), or use [Docker](https://github.com/pirate/ArchiveBox/wiki/Docker).
```bash
git clone https://github.com/pirate/ArchiveBox.git
cd ArchiveBox
./setup

# Export your bookmarks, then run the archive command to start archiving!
./archive ~/Downloads/firefox_bookmarks.html

# Or to add just one page to your archive
echo 'https://example.com' | ./archive
```

*(Recently [renamed](https://github.com/pirate/ArchiveBox/issues/108) from `Bookmark Archiver`)*


<img src="https://i.imgur.com/PVO88AZ.png"/>


# Documentation

We use the [Github wiki system](https://github.com/pirate/ArchiveBox/wiki) for documentation.

You can also access the docs locally by looking in the [`ArchiveBox/docs/`](https://github.com/pirate/ArchiveBox/wiki/Home) folder.

## Getting Started

 - [Quickstart](https://github.com/pirate/ArchiveBox/wiki/Quickstart)
 - [Install](https://github.com/pirate/ArchiveBox/wiki/Install)
 - [Docker](https://github.com/pirate/ArchiveBox/wiki/Docker)

## Reference

 - [Usage](https://github.com/pirate/ArchiveBox/wiki/Usage)
 - [Configuration](https://github.com/pirate/ArchiveBox/wiki/Configuration)
 - [Chromium Install](https://github.com/pirate/ArchiveBox/wiki/Chromium-Install)
 - [Publishing Your Archive](https://github.com/pirate/ArchiveBox/wiki/Publishing-Your-Archive)
 - [Troubleshooting](https://github.com/pirate/ArchiveBox/wiki/Troubleshooting)

## More Info

 - [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap)
 - [Changelog](https://github.com/pirate/ArchiveBox/wiki/Changelog)
 - [Donations](https://github.com/pirate/ArchiveBox/wiki/Donations)
 - [Web Archiving Community](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community)


# Background & Motivation

Vast treasure troves of knowledge are lost every day on the internet to link rot.  As a society, we have an imperative
to preserve some important parts of that treasure, just like we would the library of Alexandria or a collection of art. 

Whether it's to resist censorship by saving articles before they get taken down or editied, or
to save that collection of early 2010's flash games you love to play, having the tools to 
archive the internet enable to you save some of the content you care about before it dissapears.

The balance between the permanence and ephemeral nature of the internet is what makes it beautiful, 
I don't think everything should be preserved, and but I do think people should be able to decide
for themselves and effectively archive content in a format that will survive being passed down to
historians and archivists through many generations.

*You can read more about [why web archiving is important](https://parameters.ssrc.org/2018/09/on-the-importance-of-web-archiving/), discover the [community](https://github.com/pirate/ArchiveBox/wiki/Web-Archiving-Community), or reach out to me on [Twitter](https://twitter.com/thesquashSH) for questions and comments.*


# Screenshots

<img src="https://i.imgur.com/q3Oz9wN.png" width="75%" alt="Desktop Screenshot" align="top"><img src="https://i.imgur.com/TG0fGVo.png" width="25%" alt="Mobile Screenshot" align="top"><br/>
<img src="https://i.imgur.com/3tBL7PU.png" width="100%" alt="CLI Screenshot">

---

<div align="center">

[![Donate via Patreon](https://img.shields.io/badge/Donate-Patreon-%23DD5D76.svg?style=flat&label=Support+development+via)](https://www.patreon.com/theSquashSH) <br/><br/>
[![Twitter URL](https://img.shields.io/badge/Tweet-%40theSquashSH-blue.svg?style=flat)](https://twitter.com/thesquashSH) [![Github Stars](https://img.shields.io/github/stars/pirate/ArchiveBox.svg?style=flat&label=Github+stars)](https://github.com/pirate/ArchiveBox)

</div>
