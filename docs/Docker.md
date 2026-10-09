# Docker

For desktop browser cookies and bookmarks, see [Chrome profile setup](https://github.com/ArchiveBox/ArchiveBox/wiki/Chromium-Install#import-an-existing-browser-profile).

## Overview

Running ArchiveBox with Docker allows you to manage it in a container without exposing it to the rest of your system. ArchiveBox generally works the same in Docker as it does outside Docker. You can even use `uv`-installed ArchiveBox and Docker ArchiveBox in tandem, as they both share the same data directory format.

<img src="https://imgur.zervice.io/qFAPRwC.png" width="20%" align="right"/>

- [Overview](#overview)
- [Docker Compose](#docker-compose) ⭐️ (recommended)
  - [Setup](#setup)
  - [Upgrading](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading#upgrading-with-docker-compose-%EF%B8%8F)
  - [Usage](#usage)
  - [Accessing the data](#accessing-the-data)
  - [Configuration](#configuration)
- [Plain Docker](#docker)
  - [Setup](#setup-1)
  - [Upgrading](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading#upgrading-with-plain-docker)
  - [Usage](#usage-1)
  - [Accessing the data](#accessing-the-data-1)
  - [Configuration](#configuration-1)

<br/>

**Official Docker Hub image: [`hub.docker.com/r/archivebox/archivebox`](https://hub.docker.com/r/archivebox/archivebox)**
```bash
docker pull archivebox/archivebox:dev
```

- [`Dockerfile`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/Dockerfile)
- [`docker-compose.yml`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/docker-compose.yml)

Published [Docker tags](https://hub.docker.com/r/archivebox/archivebox/tags):
- `:dev` for unstable alpha builds (breaks often, only for developers and willing beta testers)
- `:x.xrcN` and `:x.x.xrcN` for specific RC versions
- `:sha-xxxxxxx` for builds of specific git commits (to test or pin specific PRs or commits)

<br/>

> [!IMPORTANT]
> *Make sure Docker is **[installed](https://docs.docker.com/install/#supported-platforms)** and up-to-date before following any instructions below!*  ➡️  
> Check both commands before continuing: `docker --version` and `docker compose version` (Compose v2 is required).

<br/>

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/9e8658f7-7d00-452e-a10e-f7d22ef9365a" height="40px" align="right"/>

## Docker Compose

<br/>

### Setup

A full [`docker-compose.yml`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/docker-compose.yml) file is provided with all the extras included.  
You can uncomment sections within it to enable extra features, or run the basic version as-is.


```bash
# create a folder to store your data (can be anywhere)
mkdir -p ~/archivebox/data && cd ~/archivebox

# download the compose file into the directory
curl -fsSL 'https://docker-compose.archivebox.io' > docker-compose.yml
# (shortcut for getting https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/dev/docker-compose.yml)

# pull and start the current image
# (the server initializes a new collection automatically)
docker compose pull
docker compose up -d --wait
```

Open <http://admin.archivebox.localhost:5797> and follow the setup wizard to create the first admin and configure web access. Existing `BASE_URL` and security settings are used as-is, so configured servers skip the web-access wizard.

ArchiveBox installs and enables both ripgrep and [Sonic](https://github.com/valeriansaliou/sonic). Sonic is selected by default in the UI, while ripgrep remains available as the fallback. To select ripgrep explicitly:
```bash
docker compose exec archivebox archivebox config --set SEARCH_BACKEND_ENGINE=ripgrep
```

<br/>

### Upgrading

See the wiki page on [Upgrading or Merging Archives: Upgrading with Docker Compose](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading#upgrading-with-docker-compose-%EF%B8%8F) for instructions. ➡️

<br/>

### Usage

With the server running from the setup steps above, use `docker compose exec archivebox archivebox [subcommand]` just like the non-Docker `archivebox [subcommand]` CLI. If the server is stopped, use `docker compose run --rm archivebox [subcommand]` instead.

First, make sure you're `cd`'ed into the same folder as your `docker-compose.yml` file (e.g. `~/archivebox`):
```bash
docker compose exec archivebox archivebox help
```

To add an individual URL, pass it in as an arg or via stdin:
```bash
docker compose exec archivebox archivebox add 'https://example.com'
# OR
echo 'https://example.com' | docker compose exec -T archivebox archivebox add
```

To add multiple URLs at once, pipe them in via stdin, or place them in a file inside `./data/sources` so that ArchiveBox can access it from within the container:
```bash
# pipe URLs in from a file outside Docker
docker compose exec -T archivebox archivebox add < ~/Downloads/example_urls.txt

# OR ingest URLs from a file mounted inside Docker
docker compose exec archivebox archivebox add --depth=1 /data/sources/example_urls.txt

# OR pipe in URLs from a remote source
curl 'https://example.com/some/rss/feed.xml' | docker compose exec -T archivebox archivebox add
docker compose exec archivebox archivebox add --depth=1 'https://example.com/some/rss/feed.xml'
```

The `--depth=1` flag tells ArchiveBox to look inside the provided source and archive all the URLs within:
```bash
# this archives just the RSS file itself (probably not what you want)
docker compose exec archivebox archivebox add 'https://example.com/some/feed.rss'

# this archives the RSS feed file + all the URLs mentioned inside of it
docker compose exec archivebox archivebox add --depth=1 'https://example.com/some/feed.rss'
```

<br/>

### Accessing the data

The outputted archive data is stored in `data/` (relative to the project root), or whatever folder path you specified in the `docker-compose.yml` `volumes:` section. The mounted directory must be writable by its current owner; by default the entrypoint detects that non-root owner and runs ArchiveBox with matching permissions.

<a id="puid--pgid"></a>
#### Docker `PUID` / `PGID`

`PUID` and `PGID` are optional Docker-entrypoint environment variables for mounts with a fixed numeric identity, such as NFS/CIFS/FUSE. They override owner autodetection and are not ArchiveBox config keys: do not put them in `ArchiveBox.conf` or use `archivebox config --set`. Both must be numeric. `PUID=0` is ignored in favor of the detected/default non-root UID so ArchiveBox and Chrome never run as root; `PGID=0` is permitted for a group-writable mount.

```bash
PUID=1000 PGID=1000 docker compose up -d --wait
```

Leave them unset for normal local bind mounts. When you do set them, match the effective numeric owner/group or ACL configured by the storage server; container root cannot override server-side permission enforcement such as NFS `root_squash`.

To access a result directly via the filesystem, follow its backwards-compatible `./data/archive/<timestamp>` symlink, or browse the canonical `./data/archive/users/<user>/snapshots/<date>/<domain>/<uuid>/` tree.

Alternatively, to use the web UI, start the server with:
```bash
docker compose up         # add -d to run in the background
```

Then open [`http://web.archivebox.localhost:5797`](http://web.archivebox.localhost:5797) for the public UI or [`http://admin.archivebox.localhost:5797`](http://admin.archivebox.localhost:5797) for the admin UI.

Use port **5797** for new deployments. The Docker container also listens on the old port **8000** so existing port mappings remain compatible.

<br/>

### Configuration

ArchiveBox running with `docker compose` accepts all the same config options as other ArchiveBox distributions, see the full list of options available on the [Configuration](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration) page.

The recommended way configure ArchiveBox in Docker Compose is using `archivebox config --set ...` or by editing `ArchiveBox.conf`.
```bash
docker compose exec archivebox archivebox config --set TIMEOUT=120
# OR edit ./data/ArchiveBox.conf and add this under its existing [ARCHIVING_CONFIG] section:
TIMEOUT=120

# plugin-specific options work the same way (see https://plugins.archivebox.io/)
docker compose exec archivebox archivebox config --set YTDLP_MAX_SIZE=750m
```
This will apply the config to all containers or archivebox instances that access the collection.

If you're only running one container, or if you want to scope config options to only apply to a particular container, you can set them in that container's `environment:` section:

```yaml
...

services:
    archivebox:
        ...
        environment:
            - USE_COLOR=False
            - SHOW_PROGRESS=False
            - CHECK_SSL_VALIDITY=False
            - RESOLUTION=1900,1820
            - MEDIA_TIMEOUT=512000
        ...
```

For public HTTPS, start the default stack with `docker compose up -d`, use port `5797` only as the temporary setup/upstream endpoint, and follow the first-run wizard. It gives the DNS, upstream, and certificate settings to enter in Cloudflare, Nginx Proxy Manager, Caddy, Traefik, Tailscale, or your hosting platform's ingress UI, then verifies the public HTTPS URLs before saving `BASE_URL` and `SERVER_SECURITY_MODE`.

Use exactly one of these certificate layouts:

- **Single-domain mode:** one certificate for the `BASE_URL` hostname, proxied to ArchiveBox port `5797`.
- **Isolated-subdomain mode:** one certificate covering both the `BASE_URL` hostname and `*.BASE_URL`, normally obtained through DNS-01.

Never enable on-demand TLS or request individual certificates for `snap-*` hostnames.

### Cloudflare Tunnel: production example

This is a redacted example of the running ArchiveBox deployment inspected on
2026-10-09. Domain names, tunnel identifiers, host paths, and credentials are
replaced or omitted. It uses a locally managed named tunnel, a `cloudflared`
sidecar named `argo`, and ArchiveBox on their shared Compose network:

```text
Browser → Cloudflare HTTPS → cloudflared (argo) → http://archivebox:5797
```

The live deployment uses `archivebox/archivebox:dev`,
`SERVER_SECURITY_MODE=safe-subdomains-fullreplay`, public snapshot permissions,
HTTP/2 tunnel transport, and no published ArchiveBox port. Admin, web, API, and
snapshot replay have separate hostnames. The optional `demo` alias rewrites its
origin Host to the web hostname. The wildcard route preserves the requested Host.

The example keeps that routing and the effective image entrypoint/command. It
omits unrelated services, deployment overrides, and legacy CSRF settings. The
production database stays local; its separately mounted archive storage is shown
as an optional volume. The example mounts tunnel configuration read-only and
installs only the tunnel's JSON credential with restricted permissions.

#### 1. Choose the domain and create the configuration

Use a domain managed in your Cloudflare account. `example.org` below represents a
dedicated domain with HTTPS coverage for `*.example.org`; replace it everywhere.
For `BASE_URL=https://archive.example.org`, replay hosts become
`snap-<id>.archive.example.org`: make sure your edge certificate covers that extra
level before enabling full replay; see [Cloudflare certificate coverage](https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/limitations/). Follow the setup wizard's DNS/TLS checks.
The base URL is the namespace root; open `admin.example.org` to manage the app.
This example does not route the bare apex to ArchiveBox.

Create a deployment directory on your Linux Docker host:

```bash
mkdir -p ~/archivebox-cloudflare/etc/cloudflared
cd ~/archivebox-cloudflare
```

Save this as `docker-compose.yml`:

```yaml
# Redacted production layout; certificate, tunnel, and DNS setup are below.
# Use this as the complete docker-compose.yml, not as an override.
services:
    archivebox:
        image: archivebox/archivebox:dev
        restart: unless-stopped
        # Use the image's entrypoint and server --init command.
        # No ports: cloudflared reaches port 5797 on the default Docker network.
        volumes:
            - ./data:/data
            # Production also mounts remote archive storage here. Optional:
            # - /mnt/archivebox-archive:/data/archive
        environment:
            BASE_URL: https://example.org
            SERVER_SECURITY_MODE: safe-subdomains-fullreplay
            # Matches the public demo. For a private collection, change to private
            # and set PUBLIC_INDEX=False before capturing anything.
            PERMISSIONS: public
            PUBLIC_ADD_VIEW: "False"

    argo:
        image: cloudflare/cloudflared:latest
        restart: always
        user: "65532:65532"
        command: tunnel --no-autoupdate --config /etc/cloudflared/config.yml run
        volumes:
            # Obtain the account cert.pem with: cloudflared tunnel login
            # Then: cloudflared tunnel create archivebox
            # Login saves ~/.cloudflared/cert.pem; create saves <UUID>.json there.
            # Copy only <UUID>.json here, alongside config.yml (see the credential setup below).
            # cert.pem manages tunnels/DNS; the JSON credentials run this tunnel.
            - ./etc/cloudflared:/etc/cloudflared:ro
```

Save the following as `etc/cloudflared/config.yml`:

```yaml
# Replace example.org and both placeholder UUIDs with your own values.
tunnel: 00000000-0000-4000-8000-000000000000
credentials-file: /etc/cloudflared/00000000-0000-4000-8000-000000000000.json
protocol: http2

ingress:
    # Optional public-demo alias; only this alias rewrites the origin Host header.
    - hostname: demo.example.org
      service: http://archivebox:5797
      originRequest:
          httpHostHeader: web.example.org
    - hostname: web.example.org
      service: http://archivebox:5797
    - hostname: admin.example.org
      service: http://archivebox:5797
    - hostname: api.example.org
      service: http://archivebox:5797
    # Includes snap-<id>.example.org for isolated archived JavaScript replay.
    # Preserve the requested Host here: do not rewrite all requests to web/admin.
    - hostname: "*.example.org"
      service: http://archivebox:5797
    - service: http_status:404
```

This is a standalone Compose file. Combining it with the default Compose file
would retain that file's published port. It follows the live demo's `dev` image;
select a compatible stable image or digest if you do not want development updates.
The example is intentionally public like the demo. For private evidence, set
`PERMISSIONS: private` and `PUBLIC_INDEX: "False"` before the first capture.
Cloudflare Tunnel alone is not Cloudflare Access authentication.

#### 2. Obtain the certificate and tunnel credentials

Install [cloudflared](https://developers.cloudflare.com/tunnel/downloads/) on the
Docker host, then run these commands as your normal login user. Complete the
browser authorization URL printed by `login`; on a headless host, open that URL
on your workstation and leave the host command running.

```bash
# Downloads the account certificate into ~/.cloudflared/cert.pem.
cloudflared tunnel login
# Creates a named tunnel and ~/.cloudflared/<TUNNEL_UUID>.json.
cloudflared tunnel create archivebox
```

Record the UUID printed by `create`. The account `cert.pem` authorizes tunnel and
DNS management; it is not a website TLS certificate. Keep it in the login user's
protected `.cloudflared` directory. Running the sidecar only needs the tunnel's
JSON credentials. Keep `cert.pem`, the tunnel JSON, and collection data out of Git. See Cloudflare's
[credential permissions](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/tunnel-permissions/).

From your deployment directory, replace the UUID below and install the credential
for the sidecar's UID/GID:

```bash
TUNNEL_UUID=00000000-0000-4000-8000-000000000000
sudo install -m 600 -o 65532 -g 65532 \
    "$HOME/.cloudflared/$TUNNEL_UUID.json" "etc/cloudflared/$TUNNEL_UUID.json"
chmod 755 etc/cloudflared
chmod 644 etc/cloudflared/config.yml
```

Edit `docker-compose.yml` to set your domain. Edit `etc/cloudflared/config.yml` to
replace every domain and both UUID placeholders, including the JSON filename.
Keep `service: http://archivebox:5797`: `localhost` inside `argo` is not ArchiveBox.
No origin HTTPS certificate or separate reverse proxy is needed on this Docker
network. Cloudflare handles browser-facing HTTPS.

#### 3. Route DNS and start the stack

Create routes using the same login user's account certificate. Replace the
domain, and omit the optional `demo` record if you removed that ingress rule:

```bash
cloudflared tunnel route dns archivebox admin.example.org
cloudflared tunnel route dns archivebox web.example.org
cloudflared tunnel route dns archivebox api.example.org
cloudflared tunnel route dns archivebox demo.example.org
cloudflared tunnel route dns archivebox '*.example.org'
```

Existing DNS records can conflict; inspect them instead of blindly overwriting
them. Specific records take precedence over wildcard DNS. These commands follow
Cloudflare's [locally managed tunnel workflow](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/).

```bash
docker compose config --quiet
docker compose run --rm --no-deps argo tunnel --config /etc/cloudflared/config.yml ingress validate
docker compose run --rm --no-deps argo tunnel --config /etc/cloudflared/config.yml ingress rule https://snap-0123456789ab.example.org/
docker compose up -d
docker compose ps
docker compose logs --tail=50 argo
```

Open `https://admin.example.org/admin/` to complete setup and create your admin.
Check the web UI at `https://web.example.org`, log in through the admin hostname,
and open a saved capture. Confirm its raw HTML uses a `snap-…` hostname with valid
HTTPS. A running tunnel by itself does not prove wildcard DNS, TLS, or replay
isolation works. Unmatched hostnames intentionally receive a 404.

#### Notifications and private access

This documents the origin's running tunnel and ArchiveBox configuration; it does
not export the account's Cloudflare Access or WAF policies. If you protect the
application with Access, separately authorize unattended clients with a Service
Auth policy and service token. Those credentials are different from `cert.pem`
and the tunnel JSON file. See the
[Changedetection guide](Change-Detection#cloudflare-choose-the-shortest-connection)
for notification headers and tests. Services on the same trusted Docker network
can call ArchiveBox internally with its API key.

<br/>

---

<br/>

## Docker

<br/>

### Setup

Fetch and run the ArchiveBox Docker image. Starting the server creates the initial archive automatically.

```bash
docker pull archivebox/archivebox:dev

mkdir -p ~/archivebox/data && cd ~/archivebox/data
docker run -d --name archivebox -v "$PWD:/data" -p 5797:5797 archivebox/archivebox:dev
```

Then open `/admin/` on the hostname or IP used to reach ArchiveBox (local example: <http://admin.archivebox.localhost:5797/admin/>) to create the first admin. If `BASE_URL` is not configured yet, continue through the web setup wizard.

*(You can create a collection in any directory you want, `~/archivebox/data` is just used as an example here)*

If you encounter permissions issues, make sure the mounted data directory is writable by its intended owner. Docker startup uses explicit [`PUID`/`PGID`](#docker-puid--pgid) values when supplied, otherwise the first non-root owner detected from the existing collection or the default `archivebox` user when the data directory is root-owned.

<br/>

### Upgrading

See the wiki page on [Upgrading or Merging Archives: Upgrading with plain Docker](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading#upgrading-with-plain-docker) for instructions. ➡️

<br/>

### Usage

The Docker CLI `docker run ... archivebox/archivebox:dev [subcommand]` works just like the non-Docker `archivebox [subcommand]` CLI.

First, make sure you're `cd`'ed into your collection data folder (e.g. `~/archivebox/data`).

```bash
docker run -it -v $PWD:/data archivebox/archivebox:dev help
```

To add a single URL, pass it as an arg or pipe it in via stdin:
```bash
docker run -it -v $PWD:/data archivebox/archivebox:dev add 'https://example.com'
# OR
echo 'https://example.com' | docker run -i -v $PWD:/data archivebox/archivebox:dev add
```

To archive multiple URLs at once, pass text containing URLs in via stdin:
```bash
docker run -i -v $PWD:/data archivebox/archivebox:dev add < urls.txt
# OR
curl 'https://example.com/some/rss/feed.xml' | docker run -i -v $PWD:/data archivebox/archivebox:dev add
```

You can also use the `--depth=1` flag to tell ArchiveBox to recursively archive the URLs within a provided source.
```bash
docker run -it -v $PWD:/data archivebox/archivebox:dev add --depth=1 'https://example.com/some/rss/feed.xml'
```

<br/>

### Accessing the data

The `docker run` `-v /path/on/host:/path/inside/container` flag specifies where your data dir lives on the host.

For example to use a folder on an external USB drive (instead of the current directory `$PWD` or `~/archivebox/data`):
```bash
docker run -it -v /media/USB-DRIVE/archivebox/data:/data archivebox/archivebox:dev ...
```

Then to view your data, you can look in the folder on the host `/media/USB-DRIVE/archivebox/data`, or use the Web UI:
```bash
docker run -it -v /media/USB-DRIVE/archivebox/data:/data -p 5797:5797 archivebox/archivebox:dev
# then open http://web.archivebox.localhost:5797
```

<br/>

### Configuration

The easiest way is to use `archivebox config --set KEY=value` or edit `./ArchiveBox.conf` (in your collection dir).

For example, this sets `TIMEOUT=120` as a persistent setting for the collection:
```bash
docker run -it -v $PWD:/data archivebox/archivebox:dev config --set TIMEOUT=120
# OR edit ./ArchiveBox.conf and add this under its existing [ARCHIVING_CONFIG] section:
TIMEOUT=120
```

ArchiveBox in Docker also accepts config as environment variables, see more on the [Configuration](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration) page (and the [abx-plugins config reference](https://plugins.archivebox.io/) for per-plugin options).

For example, this disables the screenshot extractor for a single run (without persisting for other runs):
```bash
docker run -it -v $PWD:/data -e SCREENSHOT_ENABLED=False archivebox/archivebox:dev add 'https://example.com'
# OR
echo 'SCREENSHOT_ENABLED=False' >> ./.env
docker run ... --env-file=./.env archivebox/archivebox:dev ...
```
