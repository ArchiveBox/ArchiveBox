# Install

ArchiveBox is primarily distributed as a Python package installed with `uv`, but it also depends on some system packages that can be installed manually or automatically with Docker. It usually takes less than ~10min to get ArchiveBox set up and running.

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/601d587d-b59f-47b9-938e-8a7fa7790176" width="20%" align="right"/>



 - *[Supported Systems](#supported-systems)*
 - Install Instructions
   - **[Option A. Docker / Docker Compose ⭐️](#option-a-docker--docker-compose-setup-%EF%B8%8F)**
   - [Option B. Automatic Setup Script](#option-b-automatic-setup-script)
   - [Option C. System Package Manager Setup](#option-c-bare-metal-setup)
     - *[Upgrading ArchiveBox to a new version](#upgrading-archivebox-to-a-new-version)*
 - *[Next Steps](#next-steps)*


## Supported Systems

<img src="https://cdn0.iconfinder.com/data/icons/flat-round-system/512/freebsd-512.png" width="5%" align="right"/>
<img src="https://assets.ubuntu.com/v1/c5cb0f8e-picto-ubuntu.svg" width="5%" align="right"/>
<img src="https://imgur.zervice.io/Ue9BI7n.png" width="5%" align="right"/>

**CPU Architectures:** `amd64` (`x86_64`), `arm64` (`aarch64`), `arm7`  
*(Including 64-bit Intel/AMD, M1/M2/etc. Macs, Raspberry Pi >= 3)*

* [**macOS:**](#macos) >=10.12 (with `uv` or Homebrew)
* [**Linux:**](#ubuntudebian) Ubuntu (>= 18.04), Debian (>= 10), etc. (with `apt`)
* [**BSD:**](#bsd) FreeBSD, OpenBSD, NetBSD etc (with `pkg`)

Other systems are not officially supported but may work with degraded functionality:

<img src="https://imgur.zervice.io/WYSb96z.png" width="6%" align="right"/>
<img src="http://files.softicons.com/download/system-icons/web0.2ama-icons-by-chrfb/png/256x256/Operating%20System%20-%20Windows.png" width="5%" align="right"/>

 * **Windows:** Via [[Docker]], Docker in WSL2, or WSL2 without Docker (not recommended)
 * [Other UNIX systems:](https://github.com/ArchiveBox/ArchiveBox#-package-manager-setup) Arch, Nix, Guix, Fedora, SUSE, Arch, CentOS, etc.

<sub>Note: Some managed binary providers do not publish `arm7` builds. Run `archivebox install` to see which compatible host or managed providers are available for your platform.</sub>

<br/>

You will also need at least 1GB of RAM, and 2GB or greater is recommended. You may be able to reduce crawl-time RAM pressure if you disable all the chrome-based archiving methods with [`CHROME_ENABLED=False`](https://archivebox.github.io/abx-plugins/#chrome) (or its `USE_CHROME` alias).

It's also recommended to use a filesystem with compression and/or [deduplication](https://www.ixsystems.com/blog/ixsystems-and-klara-systems-celebrate-valentines-day-with-a-heartfelt-donation-of-fast-dedupe-to-openzfs-and-truenas/) (e.g. [ZFS](https://openzfs.github.io/openzfs-docs/Getting%20Started/index.html) or BTRFS) for maximum efficiency.

<br/>

---

<br/>

## Option A. Docker / Docker Compose Setup ⭐️

*Docker Compose is the recommended way to get ArchiveBox, as it includes all the extras out-of-the-box and provides the best security and upgrade UX.*

1. If you don't already have docker installed, follow the official instructions to get Docker on Linux, macOS, or Windows:  
  https://docs.docker.com/install/#supported-platforms ➡️

2. Then follow the [Quickstart](https://github.com/ArchiveBox/ArchiveBox#quickstart) guide and read the [[Docker]] wiki page for next steps. ➡️

> You can also run Dockerized ArchiveBox using [UNRAID/TrueNAS/Proxmox/etc.](https://github.com/ArchiveBox/ArchiveBox#-other-options) or Kubernetes.

**More info:**
- [`Dockerfile`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/Dockerfile)
- [`docker-compose.yml`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/docker-compose.yml)
- [ArchiveBox Docker Quickstart](https://github.com/ArchiveBox/ArchiveBox#quickstart) + [Usage](https://github.com/ArchiveBox/ArchiveBox/wiki/Docker) + [Configuration](https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#configuration) + [Upgrading](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives) documentation

<br/>

---

<br/>


## Option B. Automatic Setup Script

If you're on Linux with `apt` or FreeBSD with `pkg` there is an optional auto-setup script provided.

*(or scroll further down for manual install instructions)*

```bash
curl -fsSL 'https://get.archivebox.io' | bash
# shortcut to run https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/dev/bin/setup.sh
``` 
The script uses Docker automatically when a working Docker Compose installation is available. Otherwise it shows the native `uv` install plan and pauses so you can cancel before continuing. It initializes the collection, installs ArchiveBox's runtime dependencies, and starts the server; create the first admin afterward with the command printed at the end.

<img src="https://imgur.zervice.io/VMTzm0G.png" width="99%"/>

After running the setup script, continue with the [Quickstart](https://github.com/ArchiveBox/ArchiveBox#%EF%B8%8F-next-steps) guide... ➡️

> *See here for our thoughts on the [inherent limitations of `curl | sh`](https://docs.monadical.com/s/against-curl-sh) as an install method...*

<br/>

---

<br/>

## Option C. Bare Metal Setup

If you'd rather not use [Docker](https://github.com/ArchiveBox/ArchiveBox#%EF%B8%8F-easy-setup) or our [auto-install script](https://github.com/ArchiveBox/ArchiveBox#%EF%B8%8F-easy-setup), you can follow these manual setup instructions to install ArchiveBox and its dependencies using `uv` & your system package manager of choice (e.g. `apt`, `brew`, `pkg`, `nix`, etc.).

See our [Dependencies](https://github.com/ArchiveBox/ArchiveBox#dependencies) documentation to see the full list of dependencies and how they're used. Not all the dependencies are required for all modes. If you disable some archive methods you can skip installing those dependencies — for example, if you set [`MEDIA_ENABLED=False`](https://archivebox.github.io/abx-plugins/#media) you don't need to install `yt-dlp`, and if you set [`PDF_ENABLED=False`](https://archivebox.github.io/abx-plugins/#pdf), [`SCREENSHOT_ENABLED=False`](https://archivebox.github.io/abx-plugins/#screenshot), and [`DOM_ENABLED=False`](https://archivebox.github.io/abx-plugins/#dom) you don't need `chromium`.

<img src="https://avatars0.githubusercontent.com/u/1503512?s=200&v=4" width="100px" align="right"/>

**More info:**
 - For help installing these, see the [Manual Setup](#manual-setup), [[Troubleshooting]] and [[Chromium Install]] pages.
 - For per-plugin binary and enable/disable options (CHROME_BINARY, RIPGREP_BINARY, `<plugin>_ENABLED`, etc.) see the [abx-plugins config reference](https://archivebox.github.io/abx-plugins/).



<br/>

### 1. Install `uv` or the ArchiveBox OS package

ArchiveBox itself is the only tool you need to bootstrap manually. After that, `archivebox install` resolves every runtime dependency through `abxpkg`, preferring compatible host binaries and installing managed ones only when needed.

<img src="https://imgur.zervice.io/Ue9BI7n.png" width="30px" align="right"/>

#### macOS

Make sure you have [Homebrew](https://brew.sh/) installed first.

```bash
brew install uv
uv tool install --python 3.13 --upgrade 'git+https://github.com/ArchiveBox/ArchiveBox.git@dev'
```

<img src="https://assets.ubuntu.com/v1/c5cb0f8e-picto-ubuntu.svg" width="30px" align="right"/>

#### Ubuntu/Debian-based Systems

Use the third-party ArchiveBox apt repo for the simplest bare-metal install:

```bash
echo 'deb [trusted=yes] https://archivebox.github.io/debian-archivebox dev main' | sudo tee /etc/apt/sources.list.d/archivebox.list
sudo apt update
sudo apt install archivebox

mkdir -p ~/archivebox/data
cd ~/archivebox/data
archivebox init
archivebox install
archivebox add 'https://example.com'
```

The apt package is a thin dev-channel wrapper around the normal Python install
flow. Runtime extractor
dependencies such as Chromium, yt-dlp, SingleFile, and other plugin-managed
tools are installed by `archivebox install`; use `sudo archivebox install` only
if you want it to install missing system packages via apt.

<img src="https://cdn0.iconfinder.com/data/icons/flat-round-system/512/freebsd-512.png" width="30px" align="right"/>


#### FreeBSD

```bash
sudo pkg install curl
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv tool install --python 3.13 --upgrade 'git+https://github.com/ArchiveBox/ArchiveBox.git@dev'
archivebox install
```

#### OpenBSD

```bash
doas pkg_add uv
uv tool install --python 3.13 --upgrade 'git+https://github.com/ArchiveBox/ArchiveBox.git@dev'
archivebox install
```

#### Arch Linux / Nix / Guix / etc. Other OSs

See the [Quickstart](https://github.com/ArchiveBox/ArchiveBox#-package-manager-setup) instructions for other operating systems and release channels. ➡️

<br/>


<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/65315723-adae-42e4-b8c6-e44b79165ae5" width="55px" align="right"/>

### 2. Install ArchiveBox using `uv`

If you are not using the apt package above, install ArchiveBox with `uv`.

```bash
# get the dev version of ArchiveBox
uv tool install --python 3.13 --upgrade 'git+https://github.com/ArchiveBox/ArchiveBox.git@dev'

# if the optional ldap extra must compile locally on Debian/Ubuntu, install its headers and retry
# sudo apt install build-essential libldap2-dev libsasl2-dev
```

<br/>

### 3. Install runtime dependencies using `archivebox install`

Finish installing runtime dependencies for the enabled ArchiveBox plugins.
```bash
# create a new empty folder anywhere to hold your collection, and cd into it
mkdir -p ~/archivebox/data && cd ~/archivebox/data

# instantiate the directory as an archivebox collection dir
archivebox init

# auto-install runtime dependencies such as Chromium, yt-dlp, SingleFile, etc.
archivebox install

# archive a first URL
archivebox add 'https://example.com'

# ✅ see a final detailed breakdown of all the installed dependencies and commands available
archivebox version
archivebox help
```

<br/>

### Troubleshooting

Make sure the `uv`-installed version of `archivebox` is available in your `$PATH`.
```bash
uv tool list             # show info about uv-installed tools

echo $PATH               # show the directories your system is searching for binaries
type -a archivebox       # show all installed archivebox binaries available

cd ~/archivebox/data
archivebox version       # ⭐️ show lots of useful info about installed dependencies and more
archivebox status
archivebox help
```
(ensure the version shown is the most recent available from [Releases](https://github.com/ArchiveBox/ArchiveBox/releases))  
  
ArchiveBox can be launched as `root` by setup and package-manager flows; it creates or selects the `archivebox` service account and drops privileges before writing collection data. Run collection commands such as `init`, `install`, `add`, and `status` inside the data directory. Informational commands such as `version` and `help` can run anywhere.

If you have issues getting Chromium / Google Chrome or other dependencies working with ArchiveBox, see the [[Chromium Install]] and [[Troubleshooting]] pages for more detailed instructions.

<br/>

### Next Steps: Add some URLs to archive and try out CLI / Web UI


For guides on how to import URLs from different sources into ArchiveBox, check out [Input Formats](https://github.com/ArchiveBox/ArchiveBox#input-formats) and [Preparing URLs](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive). ➡️

```bash
cd ~/archivebox/data
```
```bash
# feed in your URLs to start archiving!
archivebox add --help
archivebox add < ~/Downloads/bookmarks_export.html
```
```bash
# inspect the newly added Snapshots via the CLI
archivebox list
archivebox status
```
```bash
# OR start the webserver and view them in the Web UI
archivebox server 0.0.0.0:8000
# Visit http://web.archivebox.localhost:8000 in a browser
```
See our [[Usage]] Wiki documentation page for more examples.

<br/>

### Next Steps: *Upgrading Archivebox to a new version*

Upgrade ArchiveBox itself first; `archivebox install` will then re-resolve compatible host binaries and update any managed runtime dependencies.

```bash
# get the dev version of ArchiveBox
uv tool install --python 3.13 --upgrade 'git+https://github.com/ArchiveBox/ArchiveBox.git@dev'

# run init inside any data directories to migrate the index to the latest version
cd ~/archivebox/data
archivebox init          # update collection index & apply any migrations
archivebox install       # update runtime dependencies to latest versions
archivebox update --migrate-only  # migrate/reconcile Snapshot files and metadata
archivebox status        # check collection health after the upgrade
```

Check our more detailed [Upgrading](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives) documentation and [Release Notes](https://github.com/ArchiveBox/ArchiveBox/releases) if you run into any problems. ➡️

<br/>

---

<br/>

### Further Reading

 - Read [[Usage]] to learn how to use the ArchiveBox CLI and HTML output
 - Read [[Configuration]] to learn about the various archive method options
 - Read [[Scheduled Archiving]] to learn how to set up automatic daily archiving
 - Read [[Publishing Your Archive]] if you want to host your archive for others to access online
 - Read [[Troubleshooting]] if you encounter any problems
