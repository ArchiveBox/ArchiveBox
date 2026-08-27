# Roadmap

<img src="https://imgur.zervice.io/es97GGV.png" width="20%" align="right"/>

▶️ *Comment here to discuss the contribution roadmap:  
[Official Roadmap Discussion](https://github.com/ArchiveBox/ArchiveBox/issues/120).*

---

## Planned Specification

(this is not set in stone, just a rough estimate)

### `v0.7: Schema improvements`
 - move config loading logic into settings.py
 - move all the extractors into "plugin" style folders that register their own config
 - right now, the paths of the extractor output are scattered all over the codebase, e.g. `output.pdf` (should be moved to constants at the top of the plugin config file)
 - make out_dir, link_dir, extractor_dir, naming consistent across codebase
 - remove `timestamps` as primary keys in favor of hashes, UUIDs, or some other slug https://github.com/ArchiveBox/ArchiveBox/issues/74
 - create a migration system for folder layout independent of the index (`mv` is atomic at the FS level, so we just need a `transaction.atomic(): move(oldpath, newpath); snap.data_dir = newpath; snap.save()`)
 - make `Tag` a real model `ManyToMany` with Snapshots
 - allow multiple Snapshots of the same site over time + CLI / UI to manage those, + migration from old style `#2020-01-01` hack to proper versioned snapshots
 - upgrade from Django 3 to Django 5 https://github.com/ArchiveBox/ArchiveBox/issues/988
    
### `v0.8:  Security`
 - Add CSRF/CSP/XSS protection to rendered archive pages
 - Provide secure reverse proxy in front of archivebox server in docker-compose.yml
 - Create UX flow for users to setup session cookies / auth for archiving private sites
   - cookies for wget, curl, etc low-level commands
   - localstorage, cookies, indexedb setup for chrome archiving methods
        
### `v0.9:  Performance`
 - setup huey, break up archiving process into tasks on a queue that a worker pool executes
 - setup pyppeteer2 to wrap chrome so that it's not open/closed during each extractor

### `v1.0: Full headless browser control`
 - run user-scripts / extensions in the context of the page during archiving
 - community userscripts for unrolling twitter threads, reddit threads, youtube comment sections, etc.
 - pywb-based headless browser session recording and warc replay
 - archive proxy support
   - support sending upstream requests through an external proxy
   - support for exposing a proxy that archives all downstream traffic

...

### `v2.0 Federated or distributed archiving`
 - ZFS / merkel tree for storing archive output subresource hashes
 - DHT for assigning merkel tree hash:file shards to nodes
 - tag system for tagging certain hashes with human-readable names, e.g. title, url, tags, filetype etc.
 - distributed tag lookup system




---

### Major long-term changes
 - ✅ release **`pip`, `apt`, `pkg`, and `brew` packaged distributions** for installing ArchiveBox
 - ✅ add an **optional web GUI** for managing sources, adding new links, and viewing the archive
 - ✅ switch to django + **sqlite db with migrations system** & json/html export for managing archive schema changes and persistence
 - modularize internals to allow importing individual components
 - switch to sha256 of URL as unique link ID
 - support **storing multiple snapshots** of pages over time
 - support **custom user puppeteer scripts to run while archiving** (e.g. for expanding reddit threads, scrolling thread on twitter, etc)
 - support named collections of archived content with different user access permissions
 - support sharing archived assets via DHT + torrent / ipfs / ZeroNet / other sharing system

### Smaller planned features
 - support pushing pages to multiple 3rd party services using ArchiveNow instead of just archive.org
 - ✅ body text extraction to markdown (using ~~[fathom](https://hacks.mozilla.org/2017/04/fathom-a-framework-for-understanding-web-pages/)~~ readability and mercury)
 - featured image / thumbnail extraction
 - auto-tagging links based on important/frequent keywords in extracted text (like pocket)
 - automatic article summary paragraphs from extracted text with nlp summarization library
 - ✅ full-text search of extracted text with ~~elasticsearch/elasticlunr/ag~~ sonic and ripgrep
 - ✅ download closed-caption subtitles from Youtube and other video sites (TODO: submit the subtitle files to the full-text search index)
 - try pulling dead sites from archive.org and other sources if original is down (https://github.com/hartator/wayback-machine-downloader)
 - And more in the [issues list](https://github.com/ArchiveBox/ArchiveBox/issues/)...

---

**IMPORTANT**: *Please don't work on any of these major long-term tasks without [contacting me first](https://nicksweeting.com/blog#Contact-Me), work is already in progress for many of these, and I may have to reject your PR if it doesn't align with the existing work!*


---

## Past Releases

To see how this spec has been scheduled / implemented / released so far, read these pull requests:
 - ✅ v0.1.x pre-git-history (~2017)
 - ✅ [v0.2.x](https://github.com/ArchiveBox/ArchiveBox/tree/483a3bef9e2b1a7b80611947a3be99b0cf4f9959) (~2018/12)
 - ✅ [v0.3.x](https://github.com/ArchiveBox/ArchiveBox/pull/197) (~2019/03)
 - ✅ [v0.4.x](https://github.com/ArchiveBox/ArchiveBox/pull/207) (~2019/04)
 - ✅ [v0.5.x](https://github.com/ArchiveBox/ArchiveBox/pull/552) (~2020/11)
 - ✅ [v0.6.x](https://github.com/ArchiveBox/ArchiveBox/pull/680) (~2021/03)
 - 🏖️ `sabbatical / coding hiatus during 2022`
 - ✅ [v0.7.x](https://github.com/ArchiveBox/ArchiveBox/pull/721) (~2023/11)
 - 🛠 [v0.8.x](https://github.com/ArchiveBox/ArchiveBox/pull/1311) (~2024/05)
 - 📅 v0.9.x up next...

---

## UI / UX Improvements Planned

- https://github.com/ArchiveBox/ArchiveBox/issues/1358
- https://github.com/ArchiveBox/ArchiveBox/issues/1273
- https://github.com/ArchiveBox/ArchiveBox/issues/988
- https://github.com/ArchiveBox/ArchiveBox/issues/930

---

## New Extractors Planned

- `gallery-dl`: https://github.com/ArchiveBox/ArchiveBox/issues/564
- `forum-dl`: https://github.com/ArchiveBox/ArchiveBox/issues/1368
- `scihub-dl`: https://github.com/ArchiveBox/ArchiveBox/issues/720
- `cad-dl`: https://github.com/ArchiveBox/ArchiveBox/issues/668
- `aria2`: https://github.com/ArchiveBox/ArchiveBox/issues/1355
- `podcast-archiver`: https://github.com/ArchiveBox/ArchiveBox/issues/1357
- `bdfr`: https://github.com/ArchiveBox/ArchiveBox/issues/778
- `cutycapt` screenshots: https://github.com/ArchiveBox/ArchiveBox/issues/253
- sourcemap downloader: https://github.com/ArchiveBox/ArchiveBox/issues/1291

[ArchiveBox Developer Documentation: Contributing a New Extractor](https://github.com/ArchiveBox/ArchiveBox#contributing-a-new-extractor)

And others we're considering for the future:

### Social Media

- Instagram
  - https://github.com/instaloader/instaloader (instagram downloader)
  - https://github.com/althonos/InstaLooter (stale)
- Telegram
  - https://github.com/iyear/tdl (telegram downloader)
- TikTok
  - https://github.com/charmparticle/tiktokget (tiktok downloader using yt-dlp)
  - https://github.com/TerminalWarlord/TikTok-Downloader-Bot
  - https://github.com/n0l3r/tiktok-downloader
  - https://github.com/hansputera/tiktok-dl
  - https://github.com/naseif/tiktok-scraper
  - https://github.com/irevenko/tiktik
  - https://github.com/samirelanduk/tiktok-save
  - https://github.com/Dinoosauro/tiktok-to-ytdlp
  - https://github.com/krypton-byte/tiktok-downloader
- Twitter
  - https://github.com/HoloArchivists/twspace-dl (stale, twitter spaces archiver)


### Video/Streams

- https://github.com/soimort/you-get ⭐️
- https://github.com/lay295/TwitchDownloader
- https://github.com/ihabunek/twitch-dl
- https://github.com/iawia002/lux (generic video/audio downloader)
- https://github.com/wukko/cobalt (generic video/audio downloader)
- https://github.com/jaysonlong/webvideo-downloader (Bilibili, iQIYI, Tencent Video, MGTV and WeTV)
- https://github.com/spaam/svtplay-dl (comedy central, twitch, HBO, etc. video downloader)
- https://github.com/aajanki/yle-dl (Yle Areena Finnish broadcasting video downloader)
- https://github.com/WHTJEON/widevine-dl (encrypted widevine video downloader)

### Audio/Music

- https://github.com/nathom/streamrip (Qobuz, Tidal, Deezer and SoundCloud)
- https://github.com/0xHJK/music-dl
- https://github.com/guanguans/music-dl
- https://github.com/CharlesPikachu/musicdl
- https://github.com/iheanyi/bandcamp-dl
- https://github.com/spotDL/spotify-downloader
- https://github.com/Shabinder/SpotiFlyer
- https://github.com/SathyaBhat/spotify-dl / https://github.com/SwapnilSoni1999/spotify-dl / https://github.com/dhruv-ahuja/spoti-dl
- https://github.com/vitiko98/qobuz-dl (Qobuz music downloader)
- https://github.com/akhilrex/podgrab (stale)
- https://github.com/yaronzz/Tidal-Media-Downloader-PRO (stale)
- https://github.com/flyingrub/scdl (stale)
- https://github.com/ravishi/rdio-dl (stale, Rdio song downloader)
- https://github.com/carlosflorencio/laracasts-downloader (stale?)

### Photos/Images/Comics

- https://github.com/mikf/gallery-dl ⭐️
- https://github.com/Bionus/imgbrd-grabber (generic image board downloader like gallery-dl)
- https://github.com/Xonshiz/comic-dl (comic, anime, manga, etc. downloader)
- https://github.com/justfoolingaround/animdl (anime downloader)
- https://github.com/metafates/mangal (manga downloader)
- https://github.com/boredazfcuk/docker-icloudpd (iCloud Photos downloader)
- https://github.com/Oshan96/monkey-dl (stale? anime downloader)
- https://github.com/QianyanTech/Image-Downloader (stale?)
- https://github.com/Xonshiz/anime-dl (stale?)

### Text/Forums

- https://github.com/mikwielgus/forum-dl ⭐️
- https://github.com/AndyTheFactory/newspaper4k ⭐️
- https://github.com/AAndyProgram/SCrawler (Twitter, Reddit, Instagram, Threads, Facebook, Pinterest, nsfw sites downloader)
- https://github.com/extractus/article-extractor
- https://github.com/shadowmoose/RedditDownloader (stale?)
- https://github.com/aliparlakci/bulk-downloader-for-reddit (stale?)

### MOOC/Educational Content

- https://github.com/coursera-dl/coursera-dl
- https://github.com/rand-net/khan-dl
- https://github.com/C0D3D3V/Moodle-DL
- https://github.com/r0oth3x49/acloud-dl
- https://github.com/Puyodead1/udemy-downloader
- https://github.com/PyJun/Mooc_Downloader (stale)
- https://github.com/yann0917/dedao-dl (stale, MOOC course downloader)
- https://github.com/coursera-dl/edx-dl (stale?)
- https://github.com/SigureMo/mooc-dl (stale?)
- https://github.com/calvinhobbes23/Skillshare-DL (stale)
- https://github.com/r0oth3x49/lynda-dl (stale, Lynda.com course downloader)

### Re-Archiving / WARC Creation

- https://github.com/hartator/wayback-machine-downloader
- https://github.com/MiniGlome/Archive.org-Downloader
- https://github.com/ArchiveTeam/grab-site
- https://github.com/oduwsdl/archivenow
- https://github.com/wabarc/warcraft
- https://github.com/sul-dlss/wasapi-downloader
- https://github.com/KellyStathis/warc_downloader
- https://github.com/internetarchive/heritrix3
- https://github.com/AhmadIbrahiim/Website-downloader (wget wrapper)
- https://github.com/igrigorik/gharchive.org (stale? Github downloader)

### Other

- https://github.com/KurtBestor/Hitomi-Downloader
- https://github.com/nilaoda/BBDown
- https://github.com/biliup/biliup
- https://github.com/yutto-dev/bilili
- https://github.com/nICEnnnnnnnLee/BilibiliDown
- https://github.com/matlink/gplaycli (Google Play store Android app downloader)
- https://github.com/AlphaSlayer1964/kemono-dl (Patreon, gumroad, etc. archiver)
- https://github.com/manga-download/hakuneko
- https://github.com/cancerian0684/dli-downloader (Digital Library of India ebook downloader)
- https://github.com/tusharbabbar/gaana-dl (gaana.com bollywood song downloader)
- https://github.com/rebane2001/matterport-dl (stale? virtual house tour downloader)
