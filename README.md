# Pocket/Pinboard/Browser Bookmark Archiver <img src="https://getpocket.com/favicon.ico" height="22px"/> <img src="https://pinboard.in/favicon.ico" height="22px"/> [![Twitter URL](https://img.shields.io/twitter/url/http/shields.io.svg?style=social)](https://twitter.com/thesquashSH)

(Your own personal Way-Back Machine) [DEMO: sweeting.me/pocket](https://home.sweeting.me/pocket)

Save an archived copy of all websites you star using Pocket, Pinboard, or Browser bookmarks.  
Outputs browsable html archives of each site, a PDF, a screenshot, and a link to a copy on archive.org, all indexed in a nice html file.  
(Powered by the new [headless](https://developers.google.com/web/updates/2017/04/headless-chrome) Google Chrome and good 'ol `wget`.)  
  
NEW: Also submits each link to save on archive.org!

![](screenshot.png)

## Quickstart

```bash
./archive.py link_export.html [pocket|pinboard|bookmarks]
```

`archive.py` is a script that takes a [Pocket](https://getpocket.com/export), [Pinboard](https://pinboard.in/export/), or [Browser Bookmark](https://support.google.com/chrome/answer/96816?hl=en) html export file, and turns it into a browsable archive that you can store locally or host online.

**1. Install dependencies:** `google-chrome >= 59`,` wget >= 1.16`, `python3 >= 3.5`  ([chromium](https://www.chromium.org/getting-involved/download-chromium) >= v59 also works well, yay open source!)

```bash
# On Mac:
brew install Caskroom/versions/google-chrome-canary wget python3
echo -e '#!/bin/bash\n/Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary "$@"' > /usr/local/bin/google-chrome
chmod +x /usr/local/bin/google-chrome

# On Linux:
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
apt update; apt install google-chrome-beta python3 wget

# Check:
google-chrome --version && which wget && which python3 && echo "[√] All dependencies installed."
```

**2. Run the archive script:**

1. Get your HTML export file from [Pocket](https://getpocket.com/export), [Pinboard](https://pinboard.in/export/), [Chrome Bookmarks](https://support.google.com/chrome/answer/96816?hl=en), [Firefox Bookmarks](https://support.mozilla.org/en-US/kb/export-firefox-bookmarks-to-backup-or-transfer), or [Safari Bookmarks](http://i.imgur.com/AtcvUZA.png)
2. Clone this repo `git clone https://github.com/pirate/pocket-archive-stream`
3. `cd pocket-archive-stream/`
4. `./archive.py ~/Downloads/exported_file.html [pocket|pinboard|chrome]`

It produces a folder like `pocket/` containing an `index.html`, and archived copies of all the sites,
organized by starred timestamp.  For each sites it saves:

 - wget of site, e.g. `en.wikipedia.org/wiki/Example.html` with .html appended if not present
 - `sreenshot.png` 1440x900 screenshot of site using headless chrome
 - `output.pdf` Printed PDF of site using headless chrome
 - `archive.org.txt` A link to the saved site on archive.org

You can tweak parameters like screenshot size, file paths, timeouts, dependencies, at the top of `archive.py`.
You can also tweak the outputted html index in `index_template.html`.  It just uses python
format strings (not a proper templating engine like jinja2), which is why the CSS is double-bracketed `{{...}}`.

**Estimated Runtime:** I've found it takes about an hour to download 1000 articles, and they'll take up roughly 1GB.
Those numbers are from running it single-threaded on my i5 machine with 50mbps down.  YMMV.

**Troubleshooting:**

On some Linux distributions the python3 package might not be recent enough.
If this is the case for you, resort to installing a recent enough version manually.
```bash
add-apt-repository ppa:fkrull/deadsnakes && apt update && apt install python3.6
```
If you still need help, [the official Python docs](https://docs.python.org/3.6/using/unix.html) are a good place to start.

To switch from Google Chrome to chromium, change the `CHROME_BINARY` variable at the top of `archive.py`.
If you're missing `wget` or `curl`, simply install them using `apt` or your package manager of choice.

**Live Updating:** (coming soon... maybe...)

It's possible to pull links via the pocket API or public pocket RSS feeds instead of downloading an html export.
Once I write a script to do that, we can stick this in `cron` and have it auto-update on it's own.

For now you just have to download `ril_export.html` and run `archive.py` each time it updates. The script
will run fast subsequent times because it only downloads new links that haven't been archived already.

## Publishing Your Archive

The archive is suitable for serving on your personal server, you can upload the
archive to `/var/www/pocket` and allow people to access your saved copies of sites.


Just stick this in your nginx config to properly serve the wget-archived sites:

```nginx
location /pocket/ {
    alias       /var/www/pocket/;
    index       index.html;
    autoindex   on;
    try_files   $uri $uri/ $uri.html =404;
}
```

Make sure you're not running any content as CGI or PHP, you only want to serve static files!

Urls look like: `https://sweeting.me/archive/archive/1493350273/en.wikipedia.org/wiki/Dining_philosophers_problem`

## Info

This is basically an open-source version of [Pocket Premium](https://getpocket.com/premium) (which you should consider paying for!).
I got tired of sites I saved going offline or changing their URLS, so I started
archiving a copy of them locally now, similar to The Way-Back Machine provided
by [archive.org](https://archive.org).  Self hosting your own archive allows you to save
PDFs & Screenshots of dynamic sites in addition to static html, something archive.org doesn't do.

Now I can rest soundly knowing important articles and resources I like wont dissapear off the internet.

My published archive as an example: [sweeting.me/pocket](https://home.sweeting.me/pocket).

## Security WARNING & Content Disclaimer

Hosting other people's site content has security implications for your domain, make sure you understand
the dangers of hosting other people's CSS & JS files [on your domain](https://developer.mozilla.org/en-US/docs/Web/Security/Same-origin_policy).  It's best to put this on a domain
of its own to slightly mitigate [CSRF attacks](https://en.wikipedia.org/wiki/Cross-site_request_forgery).

You may also want to blacklist your archive in your `/robots.txt` so that search engines dont index
the content on your domain.

Be aware that some sites you archive may not allow you to rehost their content publicly for copyright reasons,
it's up to you to host responsibly and respond to takedown requests appropriately.

## TODO

 - body text extraction using [fathom](https://hacks.mozilla.org/2017/04/fathom-a-framework-for-understanding-web-pages/)
 - auto-tagging based on important extracted words
 - audio & video archiving with `youtube-dl`
 - full-text indexing with elasticsearch
 - video closed-caption downloading for full-text indexing video content
 - automatic text summaries of article with summarization library
 - feature image extraction
 - http support (from my https-only domain)
 - try wgetting dead sites from archive.org (https://github.com/hartator/wayback-machine-downloader)

## Links

 - [Hacker News Discussion](https://news.ycombinator.com/item?id=14272133)
 - [Reddit r/selfhosted Discussion](https://www.reddit.com/r/selfhosted/comments/69eoi3/pocket_stream_archive_your_own_personal_wayback/)
 - [Reddit r/datahoarder Discussion](https://www.reddit.com/r/DataHoarder/comments/69e6i9/archive_a_browseable_copy_of_your_saved_pocket/)
 - https://wallabag.org + https://github.com/wallabag/wallabag
 - https://webrecorder.io/
 - https://github.com/ikreymer/webarchiveplayer#auto-load-warcs
