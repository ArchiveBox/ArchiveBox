# Bookmark Archiver <img src="https://getpocket.com/favicon.ico" height="22px"/> <img src="https://pinboard.in/favicon.ico" height="22px"/> <img src="https://nicksweeting.com/images/bookmarks.png" height="22px"/> [![Twitter URL](https://img.shields.io/twitter/url/http/shields.io.svg?style=social)](https://twitter.com/thesquashSH)

**Browser Bookmarks (Chrome, Firefox, Safari, IE, Opera), Pocket, Pinboard, Shaarli, Delicious, Instapaper, Unmark.it**

(Your own personal Way-Back Machine) [DEMO: sweeting.me/pocket](https://home.sweeting.me/pocket)

Save an archived copy of all websites you star.
Outputs browsable html archives of each site, a PDF, a screenshot, and a link to a copy on archive.org, all indexed in a nice html file.

![](screenshot.png)

## Quickstart

**1. Get your bookmarks:**

Follow the links here to find instructions for each exporting bookmarks from each service.

 - [Pocket](https://getpocket.com/export)
 - [Pinboard](https://pinboard.in/export/)
 - [Instapaper](https://www.instapaper.com/user/export)
 - [Shaarli](http://sebsauvage.net/wiki/lib/exe/fetch.php?media=php:php_shaarli:shaarli_cap16_dragbutton.png)
 - [Unmark.it](http://help.unmark.it/import-export)
 - [Chrome Bookmarks](https://support.google.com/chrome/answer/96816?hl=en)
 - [Firefox Bookmarks](https://support.mozilla.org/en-US/kb/export-firefox-bookmarks-to-backup-or-transfer)
 - [Safari Bookmarks](http://i.imgur.com/AtcvUZA.png)
 - [Opera Bookmarks](http://help.opera.com/Windows/12.10/en/importexport.html)
 - [Internet Explorer Bookmarks](https://support.microsoft.com/en-us/help/211089/how-to-import-and-export-the-internet-explorer-favorites-folder-to-a-32-bit-version-of-windows)

 (If any of these links are broken, please submit an issue and I'll fix it)

**2. Create your archive:**

```bash
git clone https://github.com/pirate/bookmark-archiver
cd bookmark-archiver/
./setup.sh
./archive.py ~/Downloads/bookmark_export.html   # replace this path with the path to your bookmarks export file
```

You can open `service/index.html` to view your archive.  (favicons will appear next to each title once it has finished downloading)

## Manual Setup

If you don't like `sudo` running random setup scripts off the internet (which you shouldn't), you can follow these manual setup instructions:

**1. Install dependencies:** `chromium >= 59`,` wget >= 1.16`, `python3 >= 3.5`  (google-chrome >= v59 also works well, no need to install chromium if you already have Google Chrome installed)

```bash
# On Mac:
brew cask install chromium  # If you already have Google Chrome/Chromium in /Applications/, skip this command
brew install wget python3

echo -e '#!/bin/bash\n/Applications/Chromium.app/Contents/MacOS/Chromium "$@"' > /usr/local/bin/chromium  # see instructions for google-chrome below
chmod +x /usr/local/bin/chromium
```

```bash
# On Ubuntu/Debian:
apt install chromium-browser python3 wget
```

```bash
# Check that everything worked:
google-chrome --version && which wget && which python3 && echo "[√] All dependencies installed."
```

**2. Get your bookmark export file:**

Follow the instruction links above in the "Quickstart" section to download your bookmarks export file.

**3. Run the archive script:**

1. Clone this repo `git clone https://github.com/pirate/bookmark-archiver`
3. `cd bookmark-archiver/`
4. `./archive.py ~/Downloads/bookmarks_export.html`

`archive.py` is a script that takes a [Pocket-format](https://getpocket.com/export), [Pinboard-format](https://pinboard.in/export/), or [Netscape-format](https://msdn.microsoft.com/en-us/library/aa753582(v=vs.85).aspx) bookmark export file, and turns it into a browsable archive that you can store locally or host online.

You may optionally specify a third argument to `archive.py export.html [pocket|pinboard|bookmarks]` to enforce the use of a specific link parser.

### Google Chrome Instrutions:

I recommend Chromium instead of Google Chrome, since it's open source and doesn't send your data to Google.
Chromium may have some issues rendering some sites though, so you're welcome to try Google-chrome instead.
It's also easier to use Google Chrome if you already have it installed, rather than downloading Chromium all over.

```bash
# On Mac:
# If you already have Google Chrome in /Applications/, skip this brew command
brew cask install google-chrome
brew install wget python3

echo -e '#!/bin/bash\n/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome "$@"' > /usr/local/bin/google-chrome
chmod +x /usr/local/bin/google-chrome
```

```bash
# On Linux:
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
apt update; apt install google-chrome-beta python3 wget
```

2. Set the environment variable `CHROME_BINARY` to `google-chrome` before running:

```bash
env CHROME_BINARY=google-chrome ./archive.py ~/Downloads/bookmarks_export.html
```

## Details

The archiver produces a folder like `pocket/` containing an `index.html`, and archived copies of all the sites,
organized by starred timestamp.  It's Powered by the [headless](https://developers.google.com/web/updates/2017/04/headless-chrome) Chromium and good 'ol `wget`.
NEW: Also submits each link to save on archive.org!
For each sites it saves:

 - wget of site, e.g. `en.wikipedia.org/wiki/Example.html` with .html appended if not present
 - `sreenshot.png` 1440x900 screenshot of site using headless chrome
 - `output.pdf` Printed PDF of site using headless chrome
 - `archive.org.txt` A link to the saved site on archive.org

You can tweak parameters like screenshot size, file paths, timeouts, dependencies, at the top of `archive.py`.
You can also tweak the outputted html index in `index_template.html`.  It just uses python
format strings (not a proper templating engine like jinja2), which is why the CSS is double-bracketed `{{...}}`.

**Estimated Runtime:** I've found it takes about an hour to download 1000 articles, and they'll take up roughly 1GB.
Those numbers are from running it single-threaded on my i5 machine with 50mbps down.  YMMV.  Users have also reported
running it with 50k+ bookmarks with success (though it will take more RAM while running).

**Troubleshooting:**

On some Linux distributions the python3 package might not be recent enough.
If this is the case for you, resort to installing a recent enough version manually.
```bash
add-apt-repository ppa:fkrull/deadsnakes && apt update && apt install python3.6
```
If you still need help, [the official Python docs](https://docs.python.org/3.6/using/unix.html) are a good place to start.

To switch from Google Chrome to chromium, change the `CHROME_BINARY` variable at the top of `archive.py`.
If you're missing `wget` or `curl`, simply install them using `apt` or your package manager of choice.

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

**Live Updating:** (coming soon... maybe...)

It's possible to pull links via the pocket API or public pocket RSS feeds instead of downloading an html export.
Once I write a script to do that, we can stick this in `cron` and have it auto-update on it's own.

For now you just have to download `ril_export.html` and run `archive.py` each time it updates. The script
will run fast subsequent times because it only downloads new links that haven't been archived already.

## Links

 - [Hacker News Discussion](https://news.ycombinator.com/item?id=14272133)
 - [Reddit r/selfhosted Discussion](https://www.reddit.com/r/selfhosted/comments/69eoi3/pocket_stream_archive_your_own_personal_wayback/)
 - [Reddit r/datahoarder Discussion](https://www.reddit.com/r/DataHoarder/comments/69e6i9/archive_a_browseable_copy_of_your_saved_pocket/)
 - https://wallabag.org + https://github.com/wallabag/wallabag
 - https://webrecorder.io/
 - https://github.com/ikreymer/webarchiveplayer#auto-load-warcs
 - [Shaarchiver](https://github.com/nodiscc/shaarchiver) very similar project that archives Firefox, Shaarli, or Delicious bookmarks and all linked media, generating a markdown/HTML index
