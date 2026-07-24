# Chrome / Chromium Setup

ArchiveBox resolves Chrome through `abxpkg`, just like every other runtime binary. It checks compatible browsers already installed on the host first. When it finds one, it projects that exact browser into the managed runtime environment; otherwise it installs a compatible managed Chromium build.

```bash
archivebox install chrome
archivebox version
```

The resolved browser is always available through `./lib/env/bin/chromium` inside the collection. `archivebox version` shows whether it came from the host or a managed provider, along with the exact version and path.

If you need to select a specific compatible browser already installed on the host, set `CHROME_BINARY` and let the same installer validate and project it:

```bash
archivebox config --set CHROME_BINARY=google-chrome
archivebox install chrome
archivebox version
```

## Troubleshooting Chromium Install

If you encounter problems setting up Google Chrome or Chromium, see the [Troubleshooting](https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#chromiumgoogle-chrome) page.

---

# Setting Up a Chromium User Profile

You may choose to set up a Chrome/Chromium user profile in order to use your cookies/sessions to log into sites behind authentication/paywall during archiving.

*Note: not all extractors use Chrome (e.g. `wget`, `mercury`, `media`). Importing a dedicated host browser profile into a persona also exports its cookies for those extractors; directly logging in through a new ArchiveBox Chrome profile does not.*

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
        environment:
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
docker compose up -d novnc
# wait a few seconds for novnc to start...
```

3. Start ArchiveBox's Chrome inside Docker
```bash
docker compose run archivebox persona create personal
docker compose run archivebox /data/lib/env/bin/chromium --user-data-dir=/data/personas/personal/chrome_profile --profile-directory=Default --disable-gpu --disable-features=dbus --disable-dev-shm-usage --start-maximized --no-sandbox --disable-setuid-sandbox --no-zygote --disable-sync --no-first-run
```
<small>(make sure you set `DISPLAY` and keep the normal persistent `/data` volume from the Compose setup!)</small>

4. Open [`http://localhost:8080/vnc.html`](http://localhost:8080/vnc.html) in your browser. You should see a remote linux desktop shown with Chrome open, allowing you to remote-control ArchiveBox's browser. Use it to log into any sites where you want to save credentials.

5. ✅ Close the browser, stop & remove novnc, and then select the `personal` persona when archiving. Chrome-based extractors will use the saved profile and should see the sites as logged in.

```bash
# stop the archivebox and novnc containers
docker compose down
docker compose down --remove-orphans
# edit docker-compose.yml to remove/comment out the novnc: section

# test it all out by archiving something hosted on one of the domains you logged in to
docker compose run archivebox add --persona=personal 'https://private.example.com/some/site/requiring/login.html'
# check the SingleFile, Screenshot, DOM, or PDF snapshot output (only these use the Chrome profile)
# make sure the content appears as your logged-in user would see it
```

Under the hood this uses [Xvfb](https://www.x.org/releases/X11R7.6/doc/man/man1/Xvfb.1.xhtml) + [Fluxbox](http://www.fluxbox.org/) + [`novnc`](https://github.com/theasp/docker-novnc) to provide a virtual display, window manager, and VNC server + novnc websocket viewer.
<br/>

### Non-Docker Setup (Local Host)

If running ArchiveBox on your local machine without Docker, this process is fairly easy.

First, create a persona to hold the dedicated Chrome profile.

```bash
archivebox persona create personal
```

Then install/resolve Chrome and launch the projected browser with that profile dir:

```bash
archivebox install chrome
./lib/env/bin/chromium --user-data-dir="$PWD/personas/personal/chrome_profile"
```

Once it's open, log in to all the sites you want to be logged in to for archiving, then close/quit Chrome.

✅ Chrome-based extractors (e.g. Screenshot, PDF, DOM, Singlefile) use that profile whenever you archive with `--persona=personal`.

Directly logging in through this profile does not generate a `cookies.txt` for non-Chrome extractors. If those extractors need the same login state, use the recommended [`archivebox persona create --import=chrome personal`](https://github.com/ArchiveBox/ArchiveBox/wiki/Personas) workflow with a dedicated host browser profile instead; the import copies the Chrome profile and exports its cookies together.

<br/>

### Non-Docker Setup (Remote Host)

You must set up the profile using the exact same version of Chrome that ArchiveBox is running. Run `archivebox install chrome` and `archivebox version` on each machine so `abxpkg` selects and validates the browser.

**General steps:**

1. Make sure you are running the same OS and have the same version of Chrome installed as the host running ArchiveBox
2. Follow the `Non-Docker Setup (Local Host)` steps above to create the `personal` persona and Chrome profile locally
3. Create the same persona from the ArchiveBox data directory on the remote host: `archivebox persona create personal`
4. Rsync the persona's Chrome profile from your local collection into the matching remote persona: `rsync --archive ~/archivebox/data/personas/personal/chrome_profile/ remotehost:~/archivebox/data/personas/personal/chrome_profile/`

You may need to run `chown -R archivebox ~/archivebox/data/personas/personal/chrome_profile` on the remote host to make the profile editable by the `archivebox` user on that machine.

✅ Chrome-based extractors (e.g. Screenshot, PDF, DOM, Singlefile) use that profile whenever you archive with `--persona=personal`.

If non-Chrome extractors need the same login state, prefer importing a dedicated host browser profile with `archivebox persona create --import=chrome personal` so the persona receives both the Chrome profile and an exported `cookies.txt`.

---

## More Info & Troubleshooting

- https://github.com/ArchiveBox/ArchiveBox/issues/952
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#archiving-private-content
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#%EF%B8%8F-things-to-watch-out-for-%EF%B8%8F
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#publishing
- https://archivebox.github.io/abx-plugins/#chrome (CHROME_USER_DATA_DIR, CHROME_BINARY, etc.)
- https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#cookies_file
