# Chrome / Chromium Setup

ArchiveBox uses a Chromium-based browser to load pages and save screenshots, PDFs, and HTML.

## Install ArchiveBox's browser

Docker images include the browser. For an installation without Docker, run these commands from your ArchiveBox data folder:

```bash
archivebox install chrome
archivebox version
```

ArchiveBox uses a suitable installed browser or downloads one if needed. `archivebox version` shows the browser it selected.

<details>
<summary>Choose a specific installed browser</summary>

Set `CHROME_BINARY` to the browser's command or executable path, then run the installer:

```bash
archivebox config --set CHROME_BINARY=google-chrome
archivebox install chrome
```

</details>

# Setting Up a Chromium User Profile

ArchiveBox uses a browser to load pages and save their content. If a page requires you to log in, ArchiveBox needs to be logged in too. Otherwise, it may save the login screen instead of the page.

A **browser profile** stores your logins and browser settings. Importing it into ArchiveBox lets ArchiveBox view pages using your account. ArchiveBox calls its copy a **persona**. Select that persona when saving a page.

Profile importing is for **Chromium-based browsers**. The examples below use Chrome; the same workflow applies to other browsers in that family. You can also [log in using ArchiveBox's own browser](#setting-up-a-new-profile) instead of importing a profile.
<a name="docker-setup"></a>
<a name="Docker-Setup"></a>

## Import an existing browser profile

These steps cover the common setup where your browser is on your computer and ArchiveBox runs in Docker on a server. You will export the profile on your computer, transfer the exported persona directly into the server's ArchiveBox data folder with `rsync`.

You need the [ArchiveBox CLI](Install.md) on your computer and SSH access to your server. The temporary folder below is only for exporting the profile; you do not need to download your server's archive.

If ArchiveBox runs on the same computer as your browser, use your existing ArchiveBox data folder for step 1, skip step 2, and run `archivebox add --persona=personal URL` in step 3.

### 1. Export the profile on your computer

Open a page you want to save and check that you can view it while logged in. Close the browser, then create a temporary export folder:

```bash
mkdir -p ~/archivebox-profile-export
cd ~/archivebox-profile-export
archivebox init
```

**Using the CLI:**

```bash
archivebox persona create --import=chrome personal
```

`personal` is a name you choose for the persona. Replace `chrome` with your browser's import name: `chromium`, `brave`, or `edge` for those browsers. The command chooses a profile automatically; use `--profile=Default` or `--profile='Profile 1'` to select a specific one.

**Using the UI instead:** run `archivebox server` from the export folder and follow the [web UI setup](Usage.md#ui-usage). Choose **Admin → Personas & Configs → Add persona → Use a detected profile**, name it `personal`, select the browser profile, and save. You can stop this local ArchiveBox server afterward.

Both methods create `~/archivebox-profile-export/personas/personal`, ready to transfer.

<details>
<summary>My browser or profile is not detected</summary>

Check the **Profile Path** on your browser's version page (`chrome://version` in Chrome). The final folder name identifies the profile, such as `Default` or `Profile 1`.

For a browser installed in a different location, the CLI accepts `--source` for its profile path and `--browser-binary` for its executable. Run `archivebox persona create --help` for the available options. Automatic detection currently lists Chrome, Chromium, Brave, and Edge; other Chromium-based browsers need their paths supplied explicitly.

</details>

### 2. Transfer the persona to your server

Run these commands **on your computer**. Replace `user@your-server` with your SSH login and `~/archivebox/data` with your server's ArchiveBox data folder (the folder mounted at `/data` in Docker):

```bash
ssh user@your-server 'mkdir -p ~/archivebox/data/personas/personal'
rsync -av ~/archivebox-profile-export/personas/personal/ user@your-server:~/archivebox/data/personas/personal/
```

The persona is now in place. Docker uses the existing data mount; no Compose changes are needed.

<a name="non-docker-setup-remote-host"></a>

For a server without Docker, transfer to `personas/personal/` inside its ArchiveBox data folder in the same way.

### 3. Save and check the page

Connect to your server and enter the folder containing its Docker Compose file:

```bash
ssh user@your-server
cd ~/archivebox
```

Replace the example URL with the page you want to save:

```bash
docker compose exec archivebox archivebox add --persona=personal 'https://example.com/page'
```

For a server without Docker, run `archivebox add --persona=personal URL` from its data folder.

**Using the UI instead:** if `personal` is not listed yet, choose **Admin → Personas & Configs → Add persona → Blank Persona**, name it `personal`, and save. This registers the transferred folder without changing its contents. Then open **Add URL**, paste the URL, and select `personal` before starting the capture.

Open the saved screenshot or HTML. Check that it contains the content you wanted, rather than a login screen. If the site requires you to log in again later, sign in in your browser and repeat the export and transfer.

Treat imported personas and logged-in snapshots as private: they can contain account information. Review the [guidance on sharing archives](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#publishing) before publishing them.

## Setting up a new profile

Use this option if you prefer to log in through ArchiveBox's browser instead of importing a browser profile. Log in once, then select the same persona for future captures.

### Non-Docker Setup (Local Host)

From your ArchiveBox data folder:

```bash
archivebox persona create personal
archivebox persona open personal
```

Log in to the sites you want to archive, then close the browser. Save a page with `archivebox add --persona=personal URL` and check the resulting Screenshot, DOM, PDF, or SingleFile output.

### Docker VNC Setup

This opens the selected persona in a browser you can control remotely. It also works with an [imported profile](#import-an-existing-browser-profile).

1. In your [Docker Compose file](https://docker-compose.archivebox.io), uncomment the `novnc` service and the `depends_on` block under `archivebox`. Uncomment `ARCHIVEBOX_VNC_PERSONA=personal` to select your persona.

2. From the Compose folder, run:

```bash
docker compose up -d
```

ArchiveBox waits for VNC to be ready, then opens the persona's browser with its imported logins. If an ArchiveBox browser is already open on that display, it waits for that browser to close first.

3. Visit <http://localhost:8080/vnc.html> and click **Connect**. For a remote server, first run this on your computer and keep the connection open:

```bash
ssh -N -L 8080:127.0.0.1:8080 user@your-server
```

4. Open a page and confirm you can view it while logged in. For a new persona, log in to the sites you want to archive. Then follow [Save and check the page](#3-save-and-check-the-page), selecting the same persona.

#### One-off Compose setup

To set up a persona without starting the ArchiveBox server, enable the same `novnc` service and healthy `depends_on` block, then run:

```bash
docker compose up -d --wait novnc
docker compose run --rm archivebox persona create personal
docker compose run --rm -e DISPLAY=novnc:0.0 archivebox persona open personal
```

Connect at <http://localhost:8080/vnc.html>, log in, and close the browser when finished. The persona remains in `data/personas/personal` across one-off containers.

`persona open` resolves the installed Chromium binary automatically. Do not hard-code `/data/lib/env/bin/chromium` or a versioned Playwright cache path: the browser location varies by image version and architecture.

An explicitly set `DISPLAY` is preserved. When it is unset, ArchiveBox probes `novnc:0.0` and falls back to headless operation if unavailable. Set `DISPLAY=` to disable this automatic display selection.

## Troubleshooting Chromium Install

<a name="more-info--troubleshooting"></a>

- **Browser missing or unable to start:** see [Chromium troubleshooting](https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#chromiumgoogle-chrome).
- **Saved a login screen:** confirm you can view the page in the source browser, re-import the correct profile, and select that persona when saving.
- **Need browser settings:** see the [Chrome plugin configuration](https://archivebox.github.io/abx-plugins/#chrome).
