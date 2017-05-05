# Pocket Stream Archive

Save an archived copy of all websites starred using Pocket, indexed in an html file.

![](screenshot.png)

## Quickstart

**Dependencies:** Google Chrome headless, wget

```bash
brew install Caskroom/versions/google-chrome-canary
brew install wget

# OR on linux

wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
apt update; apt install google-chrome-beta
```

**Usage:**

1. Download your pocket export file `ril_export.html` from https://getpocket.com/export
2. Download this repo `git clone https://github.com/pirate/pocket-archive-stream`
3. `cd pocket-archive-stream/`
4. `./archive.py path/to/ril_export.html`

It produces a folder `pocket/` containing an `index.html`, and archived copies of all the sites,
organized by timestamp.  For each sites it saves:
    - wget of site, with .html appended if not present
    - screenshot of site using headless chrome
    - PDF of site using headless chrome

The wget archive is suitable for serving on your personal server, you can upload the pocket
archive to `/var/www/pocket` and allow people to access your saved copies of sites.


## Info

This is basically an open-source version of [Pocket Premium](https://getpocket.com/).  I got tired of sites I saved going offline,
or changing their URLS, so I want to archive a copy of them whenever I save them now.

Now I can rest soundly knowing important articles and resources I like wont dissapear off the internet.

**WARNING:**

Hosting other people's site content has security implications for your domain, make sure you understand
the dangers of hosting other people's CSS & JS files on your domain.  It's best to put this on a domain
of its own to slightly mitigate CSRF attacks.

It might also be prudent to blacklist your archive in your `robots.txt` so that search engines dont index
the content on your domain.
