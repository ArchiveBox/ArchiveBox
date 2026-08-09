# Docker

## Overview

Running ArchiveBox with Docker allows you to manage it in a container without exposing it to the rest of your system. ArchiveBox generally works the same in Docker as it does outside Docker. You can even use `uv`-installed ArchiveBox and Docker ArchiveBox in tandem, as they both share the same data directory format.

<img src="https://imgur.zervice.io/qFAPRwC.png" width="20%" align="right"/>

- [Overview](#Overview)
- [Docker Compose](#docker-compose) ⭐️ (recommended)
  - [Setup](#setup)
  - [Upgrading](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#upgrading-with-docker-compose-%EF%B8%8F)
  - [Usage](#usage)
  - [Accessing the data](#accessing-the-data)
  - [Configuration](#configuration)
- [Plain Docker](#docker)
  - [Setup](#setup-1)
  - [Upgrading](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#upgrading-with-plain-docker)
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

# pull the current image, initialize the collection, install runtime dependencies,
# then create an admin user for the Web UI (or set ADMIN_USERNAME/ADMIN_PASSWORD env vars)
docker compose pull
docker compose run archivebox init
docker compose run archivebox install
docker compose run archivebox manage createsuperuser
```

ArchiveBox installs and enables both ripgrep and [Sonic](https://github.com/valeriansaliou/sonic). Sonic is selected by default in the UI, while ripgrep remains available as the fallback. To select ripgrep explicitly:
```bash
docker compose run archivebox config --set SEARCH_BACKEND_ENGINE=ripgrep
```

<br/>

### Upgrading

See the wiki page on [Upgrading or Merging Archives: Upgrading with Docker Compose](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#upgrading-with-docker-compose-%EF%B8%8F) for instructions. ➡️

<br/>

### Usage

You can use `docker compose run archivebox [subcommand]` just like the non-Docker `archivebox [subcommand]` CLI.

First, make sure you're `cd`'ed into the same folder as your `docker-compose.yml` file (e.g. `~/archivebox`):
```bash
docker compose run archivebox help
```

To add an individual URL, pass it in as an arg or via stdin:
```bash
docker compose run archivebox add 'https://example.com'
# OR
echo 'https://example.com' | docker compose run -T archivebox add
```

To add multiple URLs at once, pipe them in via stdin, or place them in a file inside `./data/sources` so that ArchiveBox can access it from within the container:
```bash
# pipe URLs in from a file outside Docker
docker compose run -T archivebox add < ~/Downloads/example_urls.txt

# OR ingest URLs from a file mounted inside Docker
docker compose run archivebox add --depth=1 /data/sources/example_urls.txt

# OR pipe in URLs from a remote source
curl 'https://example.com/some/rss/feed.xml' | docker compose run -T archivebox add
docker compose run archivebox add --depth=1 'https://example.com/some/rss/feed.xml'
```

The `--depth=1` flag tells ArchiveBox to look inside the provided source and archive all the URLs within:
```bash
# this archives just the RSS file itself (probably not what you want)
docker compose run archivebox add 'https://example.com/some/feed.rss'

# this archives the RSS feed file + all the URLs mentioned inside of it
docker compose run archivebox add --depth=1 'https://example.com/some/feed.rss'
```

<br/>

### Accessing the data

The outputted archive data is stored in `data/` (relative to the project root), or whatever folder path you specified in the `docker-compose.yml` `volumes:` section. The mounted directory must be writable by its current owner; the entrypoint detects that non-root owner and runs ArchiveBox with matching permissions.

To access a result directly via the filesystem, follow its backwards-compatible `./data/archive/<timestamp>` symlink, or browse the canonical `./data/archive/users/<user>/snapshots/<date>/<domain>/<uuid>/` tree.

Alternatively, to use the web UI, start the server with:
```bash
docker compose up         # add -d to run in the background
```

Then open [`http://web.archivebox.localhost:8000`](http://web.archivebox.localhost:8000) for the public UI or [`http://admin.archivebox.localhost:8000`](http://admin.archivebox.localhost:8000) for the admin UI.

<br/>

### Configuration

ArchiveBox running with `docker compose` accepts all the same config options as other ArchiveBox distributions, see the full list of options available on the [[Configuration]] page.

The recommended way configure ArchiveBox in Docker Compose is using `archivebox config --set ...` or by editing `ArchiveBox.conf`.
```bash
docker compose run archivebox config --set TIMEOUT=120
# OR edit ./data/ArchiveBox.conf and add this under its existing [ARCHIVING_CONFIG] section:
TIMEOUT=120

# plugin-specific options work the same way (see https://archivebox.github.io/abx-plugins/)
docker compose run archivebox config --set YTDLP_MAX_SIZE=750m
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

You can also specify an env file via CLI when running compose using `docker compose --env-file=/path/to/config.env ...` although you must specify the variables in the `environment:` section that you want to have passed down to the ArchiveBox container from the passed env file.

If you want to access your archive server with HTTPS, the bundled `docker-compose.yml` includes two opt-in ingress profiles:

- `COMPOSE_PROFILES=https` runs Traefik in front of ArchiveBox for HTTPS/TLS, with optional wildcard certificates via DNS-01.
- `COMPOSE_PROFILES=tunnel` runs a Cloudflare Tunnel for deployments without a public IP.

Set `BASE_URL=https://archive.example.com` and `ARCHIVEBOX_PORT=127.0.0.1:8000` in the `.env` file next to `docker-compose.yml`, then follow the inline comments in the compose file for the profile you choose. The localhost port binding prevents direct HTTP access from bypassing the public HTTPS ingress. You can still bring your own reverse proxy such as Nginx or Caddy in front of `http://127.0.0.1:8000`; [`etc/nginx.conf`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/etc/nginx.conf) remains a standalone example.

<br/>

---

<br/>

## Docker

<br/>

### Setup

Fetch and run the ArchiveBox Docker image to create your initial archive.

```bash
docker pull archivebox/archivebox:dev

mkdir -p ~/archivebox/data && cd ~/archivebox/data
docker run -it -v $PWD:/data archivebox/archivebox:dev init
docker run -it -v $PWD:/data archivebox/archivebox:dev install
```

*(You can create a collection in any directory you want, `~/archivebox/data` is just used as an example here)*

If you encounter permissions issues, make sure the mounted data directory is writable by its intended owner. Docker startup automatically uses the first non-root owner detected from the existing collection, or the default `archivebox` user when the data directory is root-owned.

<br/>

### Upgrading

See the wiki page on [Upgrading or Merging Archives: Upgrading with plain Docker](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives#upgrading-with-plain-docker) for instructions. ➡️

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
docker run -it -v /media/USB_DRIVE/archivebox/data:/data -p 8000:8000 archivebox/archivebox:dev
# then open http://web.archivebox.localhost:8000
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

ArchiveBox in Docker also accepts config as environment variables, see more on the [[Configuration]] page (and the [abx-plugins config reference](https://archivebox.github.io/abx-plugins/) for per-plugin options).

For example, this disables the screenshot extractor for a single run (without persisting for other runs):
```bash
docker run -it -v $PWD:/data -e SCREENSHOT_ENABLED=False archivebox/archivebox:dev add 'https://example.com'
# OR
echo 'SCREENSHOT_ENABLED=False' >> ./.env
docker run ... --env-file=./.env archivebox/archivebox:dev ...
```
