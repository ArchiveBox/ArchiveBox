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

* [**macOS:**](#macos) >=10.12 (with `pip`)
* [**Linux:**](#ubuntudebian) Ubuntu (>= 18.04), Debian (>= 10), etc. (with `apt`)
* [**BSD:**](#bsd) FreeBSD, OpenBSD, NetBSD etc (with `pkg`)

Other systems are not officially supported but may work with degraded functionality:

<img src="https://imgur.zervice.io/WYSb96z.png" width="6%" align="right"/>
<img src="http://files.softicons.com/download/system-icons/web0.2ama-icons-by-chrfb/png/256x256/Operating%20System%20-%20Windows.png" width="5%" align="right"/>

 * **Windows:** Via [[Docker]], Docker in WSL2, or WSL2 without Docker (not recommended)
 * [Other UNIX systems:](https://github.com/ArchiveBox/ArchiveBox#-package-manager-setup) Arch, Nix, Guix, Fedora, SUSE, Arch, CentOS, etc.

<sub>Note: On `arm7` the `playwright` package is not available, so `chromium` must be installed manually if needed.</sub>

<br/>

You will also need at least 500MB of RAM (bare minimum), 2GB or greater is recommended. You may be able to reduce the RAM requirements if you disable all the chrome-based archiving methods with [`CHROME_ENABLED=False`](https://archivebox.github.io/abx-plugins/#chrome) (or its `USE_CHROME` alias).

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
set -euo pipefail; setup_script="$(mktemp)"; curl -fsSL "file://${ARCHIVEBOX_PROJECT_DIR:-$PWD}/bin/setup.sh" > "$setup_script"
bash -n "$setup_script"; cmp "$setup_script" "${ARCHIVEBOX_PROJECT_DIR:-$PWD}/bin/setup.sh"
``` 
The script explains what it installs beforehand, and will prompt for user confirmation before making any changes to your system. The script uses Docker if already installed, but you can decline and it will install ArchiveBox using `uv` instead.

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

### 1. Install base system dependencies needed for your OS

*Be aware, you'll need to keep all these packages up-to-date yourself over time!*

<img src="https://imgur.zervice.io/Ue9BI7n.png" width="30px" align="right"/>

#### macOS

Make sure you have [Homebrew](https://brew.sh/) installed first.

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
brew install uv node git wget curl ffmpeg yt-dlp ripgrep sonic
tool_root="$(mktemp -d)"; export UV_TOOL_DIR="$tool_root/tools" UV_TOOL_BIN_DIR="$tool_root/bin"
uv tool install --python 3.13 --upgrade "$project_dir"
archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
"$UV_TOOL_BIN_DIR/archivebox" init
"$UV_TOOL_BIN_DIR/archivebox" install
"$UV_TOOL_BIN_DIR/archivebox" version
brew list --versions uv node git wget curl ffmpeg yt-dlp ripgrep sonic
brew info ffmpeg >/dev/null
brew info --cask chromium >/dev/null
```

<img src="https://assets.ubuntu.com/v1/c5cb0f8e-picto-ubuntu.svg" width="30px" align="right"/>

#### Ubuntu/Debian-based Systems

Use the third-party ArchiveBox apt repo for the simplest bare-metal install:

```bash
set -euo pipefail; echo 'deb [trusted=yes] https://archivebox.github.io/debian-archivebox dev main' > /etc/apt/sources.list.d/archivebox.list
apt-get update
apt-get install -y archivebox
archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
archivebox init
archivebox install
archivebox add --plugins=parse_txt_urls "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}"
archivebox status
```

The apt package is a thin dev-channel wrapper around the normal Python install
flow. Runtime extractor
dependencies such as Chromium, yt-dlp, SingleFile, and other plugin-managed
tools are installed by `archivebox install`; use `sudo archivebox install` only
if you want it to install missing system packages via apt.

<img src="https://cdn0.iconfinder.com/data/icons/flat-round-system/512/freebsd-512.png" width="30px" align="right"/>


#### FreeBSD

```bash
set -euo pipefail; pkg install -y python313 git wget curl yt-dlp ripgrep py313-sqlite3 npm-node22 ffmpeg
pkg install -y chromium
python3.13 --version; node --version; git --version
wget --version; curl --version; yt-dlp --version; rg --version
ffmpeg -version; chromium --version
```

#### OpenBSD

```bash
set -euo pipefail; pkg_add python313 node wget git curl yt-dlp ffmpeg ripgrep chromium; python3.13 --version; node --version; chromium --version
```

#### Arch Linux / Nix / Guix / etc. Other OSs

See the [Quickstart](https://github.com/ArchiveBox/ArchiveBox#-package-manager-setup) instructions for other operating systems and release channels. ➡️

<br/>


<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/65315723-adae-42e4-b8c6-e44b79165ae5" width="55px" align="right"/>

### 2. Install ArchiveBox using `uv`

If you are not using the apt package above, install ArchiveBox with `uv`.

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
tool_root="$(mktemp -d)"; export UV_TOOL_DIR="$tool_root/tools" UV_TOOL_BIN_DIR="$tool_root/bin"
uv tool install --python 3.13 --upgrade "$project_dir"
"$UV_TOOL_BIN_DIR/archivebox" --help
```

<br/>

### 3. Install runtime dependencies using `archivebox install`

Finish installing runtime dependencies for the enabled ArchiveBox plugins.
```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"
cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox install
uv run --project "$project_dir" --no-sync archivebox add --plugins=parse_txt_urls "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}"
uv run --project "$project_dir" --no-sync archivebox version
uv run --project "$project_dir" --no-sync archivebox help
```

<br/>

### Troubleshooting

Make sure the `uv`-installed version of `archivebox` is available in your `$PATH`.
```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
uv tool list
uv run --project "$project_dir" --no-sync archivebox version
uv run --project "$project_dir" --no-sync archivebox status
uv run --project "$project_dir" --no-sync archivebox help
```
(ensure the version shown is the most recent available from [Releases](https://github.com/ArchiveBox/ArchiveBox/releases))  
  
Make sure to run `archivebox` **as an unprivileged user** (i.e. without `sudo` / not logged in as `root`).  
Make sure to run all commands, including `archivebox version`, `archivebox help`, etc. **inside a data directory** (or a new empty dir that will become a data dir).

If you have issues getting Chromium / Google Chrome or other dependencies working with ArchiveBox, see the [[Chromium Install]] and [[Troubleshooting]] pages for more detailed instructions.

<br/>

### Next Steps: Add some URLs to archive and try out CLI / Web UI


For guides on how to import URLs from different sources into ArchiveBox, check out [Input Formats](https://github.com/ArchiveBox/ArchiveBox#input-formats) and [Preparing URLs](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive). ➡️

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
```
```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
printf '%s\n' "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}" > bookmarks_export.html
uv run --project "$project_dir" --no-sync archivebox add --help; uv run --project "$project_dir" --no-sync archivebox add --plugins=parse_txt_urls < bookmarks_export.html
```
```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox list
uv run --project "$project_dir" --no-sync archivebox status
```
```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox server --help
printf 'Open http://localhost:%s\n' "${ARCHIVEBOX_DOCS_ARCHIVEBOX_PORT:-8000}"
```
See our [[Usage]] Wiki documentation page for more examples.

<br/>

### Next Steps: *Upgrading Archivebox to a new version*

Make sure all apt/brew/pkg/etc. dependencies from above are installed & up-to-date first.

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
tool_root="$(mktemp -d)"; export UV_TOOL_DIR="$tool_root/tools" UV_TOOL_BIN_DIR="$tool_root/bin"
uv tool install --python 3.13 --upgrade "$project_dir"
archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
"$UV_TOOL_BIN_DIR/archivebox" init
"$UV_TOOL_BIN_DIR/archivebox" install
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
