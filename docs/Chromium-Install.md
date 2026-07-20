# Chrome / Chromium Setup

By default, ArchiveBox looks for any existing installed version of Chrome/Chromium and uses it if found.  You can optionally install a specific version and set the environment variable `CHROME_BINARY` to force ArchiveBox to use that one, e.g.:  

 - `CHROME_BINARY=google-chrome-beta`
 - `CHROME_BINARY=/usr/bin/chromium-browser`
 - `CHROME_BINARY='/Applications/Chromium.app/Contents/MacOS/Chromium'`
 - `CHROME_BINARY='~/Library/Caches/ms-playwright/chromium-857950/chrome-mac/Chromium.app/Contents/MacOS/Chromium'`

If you don't already have Chrome installed, I recommend installing Chromium instead of Google Chrome, as it's the open-source fork of Chrome that doesn't send as much tracking data to Google.

**Detect or install a compatible Chrome/Chromium:**

<img src="https://imgur.zervice.io/FxFoIMH.jpg" width="25%" align="right"/> 

```bash
export PLUGINS=chrome
test_root="$(mktemp -d)"
export HOME="$test_root/home"
mkdir -p "$HOME"
archivebox_data="$test_root/data"
mkdir -p "$archivebox_data"
cd "$archivebox_data"
archivebox init
archivebox install chrome
archivebox version
```

## Installing Chromium

### ⭐️ Any OS (recommended)

ArchiveBox uses `abxpkg` to prefer a compatible browser already installed on the host. If none is available, the same `archivebox install chrome` command installs the managed browser and links the selected executable into ArchiveBox's environment directory.

### macOS

If a compatible Chrome app is already installed, `archivebox install chrome` detects and uses it without installing another copy.

### Ubuntu/Debian
If a compatible `chromium` or `chromium-browser` is already installed, `archivebox install chrome` detects and uses it. Otherwise it installs a compatible managed build.

## Installing Google Chrome

### macOS
If `/Applications/Google Chrome.app` is compatible, ArchiveBox detects it automatically.
### Ubuntu/Debian
If a compatible `google-chrome` is already installed, ArchiveBox detects it automatically.

## Troubleshooting Chromium Install

If you encounter problems setting up Google Chrome or Chromium, see the [Troubleshooting](https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#chromiumgoogle-chrome) page.

---

# Setting Up a Chromium User Profile

You may choose to set up a Chrome/Chromium user profile in order to use your cookies/sessions to log into sites behind authentication/paywall during archiving.

*Note: not all extractors use Chrome (e.g. `wget`, `mercury`, `media`), so [`COOKIES_FILE`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration/#cookies_file) should be set up as well after this.*

> [!WARNING]
> **We strongly recommend you use [separate burner credentials dedicated to archiving](https://docs.sweeting.me/s/cookie-dilemma),** e.g. don't provide cookies for your normal daily Facebook/Instagram/Google/etc. accounts as server responses and page content will often contain your name/email/PII, session cookies, private tokens, etc. which then get preserved in your snapshots for eternity.
>  
> Future viewers of your archive may be able to use any reflected archived session tokens to log in as you, or at the very least, associate the content with your real identity. Even if this tradeoff seems acceptable now or you plan to keep your archive data private, you may want to share a snapshot with others in the future, and snapshots are very hard to sanitize/anonymize after-the-fact!
>
> For this reason, it's best to set up dedicated fake profile accounts for each site you want to archive, and consider them burned if you ever share any of your archived snapshots of those sites with untrusted people.

<a name="docker-setup"></a>
<a name="Docker-Setup"></a>

### Docker VNC Setup

If using ArchiveBox in Docker, the easiest way to set up session credentials is by remote controlling the ArchiveBox Chrome browser over VNC, and using it to log in to the sites you want to save.

1. Enable the `novnc` server using these settings in your `docker-compose.yml`:

`docker-compose.yml`:
```yaml
services:
    archivebox:
        ...
        volumes:
            ...
            - ./data/personas/Default:/data/personas/Default
        environment:
            - CHROME_USER_DATA_DIR=/data/personas/Default/chrome_profile
            - DISPLAY=novnc:0.0
            
    novnc:
        image: theasp/novnc:latest
        environment:
            - DISPLAY_WIDTH=1920
            - DISPLAY_HEIGHT=1080
            - RUN_XTERM=no
        ports:
            - "8080:8080"
```

2. Start the `novnc` window server container
```bash
docker compose config --quiet
```

3. Start ArchiveBox's Chrome inside Docker
```bash
docker compose run --rm archivebox archivebox version
```
After confirming the image sees Chromium, launch the reported browser path with `--user-data-dir=/data/personas/Default/chrome_profile` and the display/security flags appropriate for your container. Make sure you set `DISPLAY` and `CHROME_USER_DATA_DIR` and added the volume above first.

4. Open [`http://localhost:8080/vnc.html`](http://localhost:8080/vnc.html) in your browser. You should see a remote linux desktop shown with Chrome open, allowing you to remote-control ArchiveBox's browser. Use it to log into any sites where you want to save credentials.

5. ✅ Close the browser, stop & remove novnc, and then run archivebox normally. It will use the profile stored in `CHROME_USER_DATA_DIR=/data/personas/Default/chrome_profile` going forward, you should now be able to archive sites as if you were logged in!

```bash
# stop the archivebox and novnc containers
docker compose down --remove-orphans
docker compose run --rm archivebox add --index-only 'https://example.com/profile-check'
```

Under the hood this uses [Xvfb](https://www.x.org/releases/X11R7.6/doc/man/man1/Xvfb.1.xhtml) + [Fluxbox](http://www.fluxbox.org/) + [`novnc`](https://github.com/theasp/docker-novnc) to provide a virtual display, window manager, and VNC server + novnc websocket viewer.
<br/>

### Non-Docker Setup (Local Host)

If running ArchiveBox on your local machine without Docker, this process is fairly easy.

First, tell archivebox where you want to store your Chrome profile.

```bash
test_root="$(mktemp -d)"
export HOME="$test_root/home"
mkdir -p "$HOME"
archivebox_data="$test_root/data"
mkdir -p "$archivebox_data"
cd "$archivebox_data"
archivebox init
profile_dir="$archivebox_data/personas/Default/chrome_profile"
archivebox config --set "CHROME_USER_DATA_DIR=$profile_dir"
```

Then run Chrome (with that profile dir) to open a visible browser window where you can log into things, e.g.:

<!--pytest-codeblocks:cont-->
```bash
archivebox install chrome
chrome_binary="$(archivebox shell -c 'from archivebox.machine.models import Binary; binary = Binary.objects.filter(name="chromium", status="installed").order_by("-modified_at").first(); print(binary.abspath if binary else "")' | tail -n 1)"
test -x "$chrome_binary"
archivebox config --get CHROME_USER_DATA_DIR | grep -Fq "$profile_dir"
"$chrome_binary" --version | grep -Eiq 'chrome|chromium'
```

Once it's open, log in to all the sites you want to be logged in to for archiving, then close/quit Chrome.

✅ All ArchiveBox extractors that use Chrome (e.g. Screenshot, PDF, DOM, Singlefile) should now use that profile.  
*Don't forget to set up [`COOKIES_FILE`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration/#cookies_file) for the rest!*

<br/>

### Non-Docker Setup (Remote Host)

You must set up the profile using the exact same version of chrome that ArchiveBox is running (which can be found with `archivebox version`).
You can download the latest chromium with `pip install playwright && playwright install --with-deps chromium`, or get older versions of Chrome from https://chromium.cypress.io.

**General steps:**

1. Make sure you are running the same OS and have the same version of Chrome installed as the host running ArchiveBox
2. Follow the `Non-Docker Setup (Local Host)` setups above to create a Chrome profile locally
3. Rsync your chrome profile from your local machine to the remote archivebox host  
   `rsync --archive /path/to/profile remotehost:/path/to/profile/on/remote/host`
4. Configure ArchiveBox on the remote host to use the `rsync`'ed Chrome profile  
   `archivebox config --set CHROME_USER_DATA_DIR=/path/to/profile/on/remote/host`

You may need to run `chown -R archivebox /path/to/profile/on/remote/host` on the remote host to make the profile editable by the `archivebox` user on that machine.

✅ All ArchiveBox extractors that use Chrome (e.g. Screenshot, PDF, DOM, Singlefile) should now use that profile.  
*Don't forget to set up [`COOKIES_FILE`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration/#cookies_file) for the rest!*

---

## More Info & Troubleshooting

- https://github.com/ArchiveBox/ArchiveBox/issues/952
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#archiving-private-content
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#%EF%B8%8F-things-to-watch-out-for-%EF%B8%8F
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#publishing
- https://archivebox.github.io/abx-plugins/#chrome (CHROME_USER_DATA_DIR, CHROME_BINARY, etc.)
- https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#cookies_file
