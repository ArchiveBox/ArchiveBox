![Logo](https://i.imgur.com/PVO88AZ.png)

# ArchiveBox <br/> The open source self-hosted web archive <img src="https://nicksweeting.com/images/archive.png" height="22px"/>  [![Github Stars](https://img.shields.io/github/stars/pirate/bookmark-archiver.svg)](https://github.com/pirate/ArchiveBox) [![Twitter URL](https://img.shields.io/twitter/url/http/shields.io.svg?style=social)](https://twitter.com/thesquashSH)


### (Recently [renamed](https://github.com/pirate/ArchiveBox/issues/108) from `Bookmark Archiver`)


    "Your own personal Way-Back Machine"

💻 [Demo](https://archive.sweeting.me) | [Website](https://archivebox.io/) | [Source](https://github.com/pirate/ArchiveBox/tree/master) | [Changelog](https://github.com/pirate/ArchiveBox/wiki/Changelog) | [Roadmap](https://github.com/pirate/ArchiveBox/wiki/Roadmap)

▶️ [Quickstart](https://github.com/pirate/ArchiveBox/wiki/Quickstart) | [Details](https://github.com/pirate/ArchiveBox/wiki) | [Configuration](https://github.com/pirate/ArchiveBox/wiki/Configuration) | [Troubleshooting](https://github.com/pirate/ArchiveBox/wiki/Troubleshooting)

---

ArchiveBox saves an archived copy of the websites you visit into a local browsable folder (the actual *content* of each site, not just the list of links).  It can archive your entire browsing history, or import links from bookmarks managers, rss, text files and more.

### Can import links from:

 - <img src="https://nicksweeting.com/images/bookmarks.png" height="22px"/> Browser history or bookmarks (Chrome, Firefox, Safari, IE, Opera)
 - <img src="https://getpocket.com/favicon.ico" height="22px"/> Pocket
 - <img src="https://pinboard.in/favicon.ico" height="22px"/> Pinboard
 - <img src="https://nicksweeting.com/images/rss.svg" height="22px"/> RSS or plain text lists
 - Shaarli, Delicious, Instapaper, Reddit Saved Posts, Wallabag, Unmark.it, and more!

### Can save these things for each site:

- Favicon
- Browsable static HTML archive (wget)
- PDF (Chrome headless)
- Screenshot (Chrome headless)
- HTML DUMP after 2s of JS running in Chrome headless
- Git repo download (git clone)
- Media download (youtube-dl: video, audio, subtitles, including playlists)
- WARC archive (wget warc)
- Submits URL to archive.org
- Index summary pages: index.html & index.json

The archiving is additive, so you can schedule `./archive` to run regularly and pull new links into the index.
All the saved content is static and indexed with JSON files, so it lives forever & is easily parseable, it requires no always-running backend.

[DEMO: archive.sweeting.me](https://archive.sweeting.me) 网站存档 / 爬虫

```bash
git clone https://github.com/pirate/ArchiveBox.git
cd ArchiveBox
./setup

# Export your bookmarks, then run the archive command to start archiving!
./archive ~/Downloads/firefox_bookmarks.html

# Or to add just one page to your archive
echo 'https://example.com' | ./archive
```


# Documentation

We use the [Github wiki system](https://github.com/pirate/ArchiveBox/wiki) for documentation.

You can also access the docs locally by looking in the [`ArchiveBox/docs/`](https://github.com/pirate/ArchiveBox/wiki/Home) folder.

## Getting Started

 - [Details & Motivation](https://github.com/pirate/ArchiveBox/wiki)
 - [Quickstart](https://github.com/pirate/ArchiveBox/wiki/Quickstart)
 - [Install](https://github.com/pirate/ArchiveBox/wiki/Install)

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

# Screenshots

<img src="https://i.imgur.com/q3Oz9wN.png" width="75%" alt="Desktop Screenshot" align="top"><img src="https://i.imgur.com/TG0fGVo.png" width="25%" alt="Mobile Screenshot" align="top"><br/>
<img src="https://i.imgur.com/3tBL7PU.png" width="100%" alt="CLI Screenshot">

---

[![](https://img.shields.io/badge/Donate-Patreon-%23DD5D76.svg)](https://www.patreon.com/theSquashSH)[![Twitter URL](https://img.shields.io/twitter/url/http/shields.io.svg?style=social)](https://twitter.com/thesquashSH)
