# Security Overview

> *💬 We offer [consulting services](https://docs.monadical.com/s/archivebox-consulting-services) to set up, secure, and maintain ArchiveBox on your preferred hosting environment.*  
> <sub>We use this revenue (from corporate clients who can afford to pay) to support open source development and keep ArchiveBox free.</sub>

## Web UI Permissions

```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox config --set PUBLIC_INDEX=False && uv run --project "$project_dir" --no-sync archivebox config --set PUBLIC_ADD_VIEW=False
uv run --project "$project_dir" --no-sync archivebox config --set PERMISSIONS=private
uv run --project "$project_dir" --no-sync archivebox manage createsuperuser --help && uv run --project "$project_dir" --no-sync archivebox manage changepassword --help
```

See [[Setting Up Authentication]] for more...

<br/>

## ArchiveBox Use-Cases

<br/>

<img src="https://imgur.zervice.io/K3dZcjG.png" width="50px" align="right"/>

#### Archiving Public Content Only ⭐️ `[Default, recommended for most people]`

This is the default (lax) mode, intended for archiving public (non-secret) URLs without authenticating the headless browser.  This is the mode used if you're archiving news articles, audio, video, etc. browser bookmarks to a folder published on your webserver. This allows you to access and link to content on `http://your.archive.com/archive...` after the originals go down.

The default mode should not be used for archiving entire browser history or authenticated private content like Google Docs, paywalled content, invite-only subreddits, private photo share urls, etc.

```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox config --set ARCHIVEDOTORG_ENABLED=True
uv run --project "$project_dir" --no-sync archivebox config --set CHROME_ISOLATION=snapshot
uv run --project "$project_dir" --no-sync archivebox config --set COOKIES_FILE=None
```


<br/>

#### Archiving Content Behind Log-Ins 🚨 `[Advanced users only]`

ArchiveBox is able to archive content that requires authentication or cookies, but it comes with some caveats. Create dedicated logins for archiving to access paywalled content, private forums, LAN-only content, etc. then share them with ArchiveBox via Chrome profile + cookies.txt file.

```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cookies_file="$(mktemp)"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init; uv run --project "$project_dir" --no-sync archivebox persona create personal
uv run --project "$project_dir" --no-sync archivebox config --set ARCHIVEDOTORG_ENABLED=False && uv run --project "$project_dir" --no-sync archivebox config --set COOKIES_FILE="$cookies_file"
uv run --project "$project_dir" --no-sync archivebox add --plugins=parse_txt_urls --persona=personal "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}"
```

To get started, set [`CHROME_USER_DATA_DIR`](https://archivebox.github.io/abx-plugins/#chrome) and [`COOKIES_FILE`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#cookies_file) to point to a Chrome user folder that has your sessions and a wget `cookies.txt` file respectively.

➡️ For full instructions on setting up a Chromium user profile see here: https://github.com/ArchiveBox/ArchiveBox/wiki/Chromium-Install#setting-up-a-chromium-user-profile

If you're importing private links or authenticated content, you probably don't want to share your archive folder publicly on a webserver, so don't follow the [[Publishing Your Archive]] instructions unless you are only serving it on a trusted LAN or have some sort of authentication in front of it.  Make sure to point ArchiveBox to an output folder with conservative permissions, as it may contain archived content with secret session tokens or pieces of your user data.  You may also wish to encrypt the archive using an encrypted disk image or filesystem like ZFS as it will contain all requests and response data, including session keys, user data, usernames, etc.

#### ⚠️ Things to watch out for: ⚠️

- any cookies / secret state present in a Chrome user profile or `cookies.txt` file may be reflected in server responses and saved in the Snapshot output (e.g. in [`headers`](https://archivebox.github.io/abx-plugins/#headers) extractor output) — visible in cleartext to anyone viewing the Snapshot. **Don't use your personal Chrome profile for archiving** or people viewing your archive can then authenticate as you.
- any secret tokens embedded in URLs (e.g. secret invite links, Google Doc URLs, etc.) will be visible on `archive.org` as the URLs are not filtered when saving to it. Disable submitting to Archive.org entirely with [`ARCHIVEDOTORG_ENABLED=False`](https://archivebox.github.io/abx-plugins/#archivedotorg).
- the domain portion in archived URLs is sent to a favicon service in order to retrieve an icon more reliably than a janky internal implementation would be able to (if leaking domains is a concern, you can change the [`FAVICON_PROVIDER`](https://archivebox.github.io/abx-plugins/#favicon) or disable favicon fetching entirely with [`FAVICON_ENABLED=False`](https://archivebox.github.io/abx-plugins/#favicon)).
- [viewing malicious archived JS could allow an attacker to access your other archive items + the admin interface](https://github.com/ArchiveBox/ArchiveBox/issues/239) — use the default [`SERVER_SECURITY_MODE=safe-subdomains-fullreplay`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#server_security_mode) (which scopes admin cookies away from snapshot replay subdomains), or disable risky extractors entirely with [`WGET_ENABLED=False`](https://archivebox.github.io/abx-plugins/#wget) and [`DOM_ENABLED=False`](https://archivebox.github.io/abx-plugins/#dom).

<br/>
<img src="https://imgur.zervice.io/Jszo4h2.png" width="400px"/>

*An example of a session cookie reflected in `headers.json` visible in the archive.*

<img src="https://imgur.zervice.io/DfyQUDV.png" width="50px" align="right"/>
<br/>

---

<br/>

### Publishing

> [!CAUTION]
> Re-hosting untrusted archived content on a domain can potentially compromise *all apps on that domain*!  
> (including other subdomains)

Make sure you thoroughly understand the dangers of [hosting untrusted HTML/JS/CSS that may be captured during archiving](https://developer.mozilla.org/en-US/docs/Web/Security/Same-origin_policy), and how viewing it can enable [CSRF attacks](https://en.wikipedia.org/wiki/Cross-site_request_forgery) across all apps on the same domain. If a logged-in user happens to visit an archived page with malicious Javascript embedded, it would allow the JS to hijack any cookies on the domain and pretend to be them, potentially exfiltrating or modifying other Snapshots/data on your server.

(This is why we don't support serving ArchiveBox from a subdirectory like `myapps.example.com/archivebox/`, it's too dangerous to share domains)

The industry standard approach is to use a separate domain for untrusted content, for example Github uses `githubusercontent.com` and Google uses `googleusercontent.com` for all user-uploaded files. If hosting ArchiveBox publicly, do the same and keep it on an isolated domain in order to mitigate potential damage of leaked cookies, CORS, and CSRF attacks.  

To protect the Admin dashboard, it's also recommended to serve all content under `/archive/` on a separate domain from `/admin/`. We do this on our servers using a simple redirect rule in nginx/cloudflare like so:

- https://demo.archivebox.io: only serves `/`, redirects `/archive/*` to `demo-static.`
- https://demo-static.archivebox.io: only serves `/archive/`, redirects everything else to `demo.`

<img width="400" alt="Cloudflare redirect rule for /archive/ to be served by a separate domain" src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/9c77f503-0d97-4a8d-810f-1f4400c7aa3e">

Published archives automatically include a `robots.txt` `Disallow: /` to block search engines from indexing them. You may still wish to publish your contact info in the index footer though using [`FOOTER_INFO`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#footer_info) so that you can respond to any DMCA and copyright takedown notices if you accidentally rehost copyrighted content.

⚠️ Make sure to read all the warnings [above](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#%EF%B8%8F-things-to-watch-out-for-%EF%B8%8F) about the dangers of exposing Chrome profile data, cookies, secret tokens in URLs, and the risks of viewing archived JS on a shared origin before publishing your archive.

More info:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive
- https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive#security-concerns
- https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive#copyright-concerns
- https://en.wikipedia.org/wiki/Cross-site_request_forgery
- https://github.com/ArchiveBox/ArchiveBox/issues/239

<br/>

---

<br/>

## Do not run as root

<img src="https://imgur.zervice.io/yDqJc4I.jpg" width="150px" align="right"/>

> [!WARNING]
> **Did you run a command in Docker with `exec` instead of `run` by accident and end up here?**  
> Make sure you use `docker run` instead of `docker exec` to run ArchiveBox commands.  
>   
> *For example:*  
> ✅ `docker compose run archivebox manage createsuperuser`  
> ✅ `docker run -it -v $PWD:/data archivebox/archivebox manage createsuperuser`  
> (`docker run` automatically uses the correct `archivebox` user & file permissions enforced via [`./bin/docker_entrypoint.sh`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/bin/docker_entrypoint.sh))  
>   
> *instead of:*  
> ❌ `docker compose exec archivebox manage createsuperuser`  
> ❌ `docker exec -it archivebox manage createsuperuser`  
> (`docker exec` will skip the [entrypoint](https://github.com/ArchiveBox/ArchiveBox/blob/dev/bin/docker_entrypoint.sh) and attempt to run everything as root and fail)  
>   
> If you must use `exec` for some reason (e.g. if you only have access to a live container shell), you can run `su archivebox` within the shell, or add the arg `--user=archivebox` after `exec`.

Do not run ArchiveBox as root for a number of reasons:
 - Chrome will execute as root and fail immediately because Chrome sandboxing is pointless when the data directory is opened as root (do not set [`CHROME_SANDBOX=False`](https://archivebox.github.io/abx-plugins/#chrome) just to bypass that error!)
 - All dependencies will be run as root, if any of them have a vulnerability that's exploited by sites you're archiving you're opening yourself up to full system compromise
 - ArchiveBox does lots of HTML parsing, filesystem access, and shell command execution.  A bug in any one of those subsystems could potentially lead to deleted/damaged data on your hard drive, or full system compromise unless restricted to a user that only has permissions to access the directories needed
 - Do you really trust a project created by a Github user called `@pirate` 😉? Why give a random program off the internet root access to your entire system? (I don't have malicious intent, I'm just saying in principle you should not be running random Github projects as root)

**Instead, you should run ArchiveBox under a separate user account with less privileged access:**
```bash
getent group archivebox >/dev/null || groupadd --system archivebox
created_archivebox_user=false; if ! id archivebox >/dev/null 2>&1; then useradd --system --gid archivebox --create-home archivebox; created_archivebox_user=true; fi; trap 'if [ "$created_archivebox_user" = true ]; then userdel --remove archivebox >/dev/null 2>&1 || true; fi' EXIT
archivebox_home="$(getent passwd archivebox | cut -d: -f6)"; mkdir -p "$archivebox_home/data"; chown -R archivebox:archivebox "$archivebox_home"
uv_binary="$(command -v uv)"; sudo -u archivebox env HOME="$archivebox_home" DATA_DIR="$archivebox_home/data" "$uv_binary" run --project "$ARCHIVEBOX_PROJECT_DIR" --no-sync archivebox init
sudo -u archivebox env HOME="$archivebox_home" DATA_DIR="$archivebox_home/data" "$uv_binary" run --project "$ARCHIVEBOX_PROJECT_DIR" --no-sync archivebox add --plugins=parse_txt_urls "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}"
```

~~If you absolutely must run it as root for some reason, a footgun is provided: you can set `ALLOW_ROOT=True` via environment variable or in your ArchiveBox.conf file.~~ This footgun option was removed (I'm sorry, the support burden of helping people who messed up their systems by running everything as root was too high).

<img src="https://imgur.zervice.io/ca1he6I.png" width="40px" align="right"/>

<br/>

---

<br/>

## Output Folder

### Database

The ArchiveBox database is an unencrypted, uncompressed SQLite3 `index.sqlite3` file on disk, and such does not require an authenticated admin SQL login to access (like PostgreSQL/MySQL would). Make sure to protect your database file adequately as anyone who can read it can read your entire collection contents. Passwords for the admin users are stored as salted and PBKDF2 hashed strings in the `auth_user` table.

More info:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#disk-layout
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#database-troubleshooting
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#modify-the-archivebox-sqlite3-db-directly
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#example-adding-a-new-user-with-a-hashed-password

### Filesystem

How much are you planning to archive?  Only a few bookmarked articles, or thousands of pages of browsing history a day?  If it's only 1-50 pages a day, you can probably just stick it in a normal folder on your hard drive, but if you want to go over 100 pages a day, you will likely want to put your archive on a compressed/deduplicated/encrypted disk image or filesystem like ZFS. Other distributed/networked/checksummed filesystems that have also been reported to work (but are not technically officially supported) include SMB, NFS, Ceph, Unraid, and BTRFS. Make sure the filesystem you're using supports FSYNC. Some filesystems are unable to store more than a certain number of directory entries, and your total number of snapshots in `./archive` may be capped as a result. Some other filesystems begin to have performance degradations but continue to function when the directory entry count gets too high. Generally this isn't an issue unless you have more than ~20,000 Snapshot folders in `./archive`.

#### Purging entries

Unless `--yes --delete` is passed to `archivebox remove`, Snapshots removed from the index remain in the filesystem and their `./archive/<timestamp>` folders need to be deleted manually to be fully removed. Imported URLs are also logged separately in `./sources`, `./logs`, and the Sonic full-text index `./sonic` and should be removed manually as well to clear all traces of a URL added by accident. You can search for a URL on the filesystem you're trying to remove using `grep -a -r "https://example.com/url/to/search/for"`.

#### Permissions

Consider what permissioning to apply to your archive folder carefully. Limit access to the fewest possible users by checking folder ownership and setting [`OUTPUT_PERMISSIONS`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#output_permissions) accordingly. Generally the `index.sqlite3` file, `archive/` folder, and `ArchiveBox.conf` file must all be owned and writable by the `archivebox` user or a dedicated non-root user.

When running with Docker, the entrypoint uses the existing non-root owner of the mounted data directory when possible, otherwise it falls back to the image's `archivebox` user.

More info:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#disk-layout
- https://github.com/ArchiveBox/ArchiveBox#output-formats
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#database-troubleshooting
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#filesystem-doesnt-support-fsync-eg-network-mounts
- https://github.com/ArchiveBox/ArchiveBox#storage-requirements
