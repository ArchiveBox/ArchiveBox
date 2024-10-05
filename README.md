<div align="center" style="text-align: center; width: 100%">
<img src="https://archivebox.io/icon.png" height="90px"/>
<h1>ArchiveBox<br/><sub>Open-source self-hosted web archiving.</sub></h1>

<br/>

▶️ <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart">Quickstart</a> | <a href="https://demo.archivebox.io">Demo</a> | <a href="https://github.com/ArchiveBox/ArchiveBox">GitHub</a> | <a href="https://github.com/ArchiveBox/ArchiveBox/wiki">Documentation</a> | <a href="#background--motivation">Info & Motivation</a> | <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community">Community</a>

<br/>

<!--<a href="http://webchat.freenode.net?channels=ArchiveBox&uio=d4"><img src="https://img.shields.io/badge/Community_chat-IRC-%2328A745.svg"/></a>-->

<a href="https://github.com/ArchiveBox/ArchiveBox/blob/dev/LICENSE"><img src="https://img.shields.io/badge/Open_source-MIT-green.svg?logo=git&logoColor=green"/></a> <a href="https://github.com/ArchiveBox/ArchiveBox/commits/dev"><img src="https://img.shields.io/github/last-commit/ArchiveBox/ArchiveBox.svg?logo=Sublime+Text&logoColor=green&label=Active"/></a> &nbsp; <a href="https://github.com/ArchiveBox/ArchiveBox"><img src="https://img.shields.io/github/stars/ArchiveBox/ArchiveBox.svg?logo=github&label=Stars&logoColor=blue"/></a> &nbsp; <a href="https://hub.docker.com/r/archivebox/archivebox"><img src="https://img.shields.io/docker/pulls/archivebox/archivebox.svg?label=Docker+Pulls"/></a> <a href="https://pypi.org/project/archivebox/"><img src="https://img.shields.io/pypi/dm/archivebox?label=PyPI%20Installs&color=%235f7dae"/></a> <a href="https://chromewebstore.google.com/detail/archivebox-exporter/habonpimjphpdnmcfkaockjnffodikoj"><img src="https://img.shields.io/chrome-web-store/users/habonpimjphpdnmcfkaockjnffodikoj?label=Chrome%20Store&color=%231973e8"/></a>

<!--<pre lang="bash" align="left"><code style="white-space: pre-line; text-align: left" align="left">
curl -fsSL 'https://get.archivebox.io' | sh    # (or see pip/brew/Docker instructions below)
</code></pre>-->

</div>
<hr/>
<br/>

**ArchiveBox is a powerful, self-hosted internet archiving solution to collect, save, and view websites offline.**

Without active preservation effort, everything on the internet eventually disappears or degrades. Archive.org does a great job as a centralized service, but saved URLs have to be public, and they can't save every type of content.

*ArchiveBox is an open source tool that lets organizations & individuals archive both public & private web content while retaining control over their data. It can be used to save copies of bookmarks, preserve evidence for legal cases, backup photos from FB/Insta/Flickr or media from YT/Soundcloud/etc., save research papers, and more...*
<br/>

> ➡️ Get ArchiveBox with `pip install archivebox` on [Linux](#quickstart), [macOS](#quickstart), and [Windows](#quickstart) (WSL2), or via **[Docker](#quickstart)** ⭐️.  

*Once installed, it can be used as a [CLI tool](#usage), [self-hosted Web App](https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive), [Python library](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#python-shell-usage), or [one-off command](#static-archive-exporting).*

<br/>
<hr/>
<br/>

📥 **You can feed ArchiveBox URLs one at a time, or schedule regular imports** from your bookmarks or history, social media feeds or RSS, link-saving services like Pocket/Pinboard, our [Browser Extension](https://github.com/ArchiveBox/archivebox-browser-extension), and more.  
<sub>See <a href="#input-formats">Input Formats</a> for a full list of supported input formats...</sub>

<br/>

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/90f1ce3c-75bb-401d-88ed-6297694b76ae" alt="snapshot detail page" align="right" width="190px" style="float: right"/>

**It saves snapshots of the URLs you feed it in several redundant formats.**  
It also detects any content featured *inside* pages & extracts it out into a folder:
- 🌐 **HTML**/**Any websites** ➡️ `original HTML+CSS+JS`, `singlefile HTML`, `screenshot PNG`, `PDF`, `WARC`, `title`, `article text`, `favicon`, `headers`, ...
- 🎥 **Social Media**/**News** ➡️ `post content TXT`, `comments`, `title`, `author`, `images`, ...
- 🎬 **YouTube**/**SoundCloud**/etc. ➡️ `MP3/MP4`s, `subtitles`, `metadata`, `thumbnail`, ...
- 💾 **Github**/**Gitlab**/etc. links ➡️ `clone of GIT source code`, `README`, `images`, ...
- ✨ *and more, see [Output Formats](#output-formats) below...*

You can run ArchiveBox as a Docker web app to manage these snapshots, or continue accessing the same collection using the `pip`-installed CLI, Python API, and SQLite3 APIs. 
All the ways of using it are equivalent, and provide matching features like adding tags, scheduling regular crawls, viewing logs, and more...

<br/>
<hr/>

🛠️ ArchiveBox uses [standard tools](#dependencies) like Chrome, [`wget`](https://www.gnu.org/software/wget/), & [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), and stores data in [ordinary files & folders](#archive-layout).  
*(no complex proprietary formats, all data is readable without needing to run ArchiveBox)*

The goal is to sleep soundly knowing the part of the internet you care about will be automatically preserved in durable, easily accessible formats [for decades](#background--motivation) after it goes down.


<hr/>
<br/>


**📦&nbsp; Install ArchiveBox using your preferred method: `docker` / `pip` / `apt` / etc. ([see full Quickstart below](#quickstart)).**


<details>
&nbsp; <summary><i>Expand for quick copy-pastable install commands...</i> &nbsp; ⤵️</summary>
<br/>
<pre lang="bash"><code style="white-space: pre-line"># Option A: Get ArchiveBox with Docker Compose (recommended):
mkdir -p ~/archivebox/data && cd ~/archivebox
curl -fsSL 'https://docker-compose.archivebox.io' > docker-compose.yml   # edit options in this file as-needed
docker compose run archivebox init --setup
# docker compose run archivebox add 'https://example.com'
# docker compose run archivebox help
# docker compose up
<br/>
<br/>
# Option B: Or use it as a plain Docker container:
mkdir -p ~/archivebox/data && cd ~/archivebox/data
docker run -it -v $PWD:/data archivebox/archivebox init --setup
# docker run -it -v $PWD:/data archivebox/archivebox add 'https://example.com'
# docker run -it -v $PWD:/data archivebox/archivebox help
# docker run -it -v $PWD:/data -p 8000:8000 archivebox/archivebox
<br/>
<br/>
# Option C: Or install it with your preferred pkg manager (see Quickstart below for apt, brew, and more)
pip install archivebox
mkdir -p ~/archivebox/data && cd ~/archivebox/data
archivebox init --setup
# archivebox add 'https://example.com'
# archivebox help
# archivebox server 0.0.0.0:8000
<br/>
<br/>
# Option D: Or use the optional auto setup script to install it
curl -fsSL 'https://get.archivebox.io' | sh
</code></pre>
<br/>
<sub>Open <a href="http://localhost:8000"><code>http://localhost:8000</code></a> to see your server's Web UI ➡️</sub>
</details>
<br/>


<div align="center" style="text-align: center">
<br/><br/>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/5a7d95f2-6977-4de6-9f08-42851a1fe1d2" height="70px" alt="bookshelf graphic"> &nbsp; <img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/b2765a33-0d1e-4019-a1db-920c7e00e20e" height="75px" alt="logo" align="top"/> &nbsp; <img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/5a7d95f2-6977-4de6-9f08-42851a1fe1d2" height="70px" alt="bookshelf graphic">
<br/><br/>
<small><a href="https://demo.archivebox.io">Demo</a> | <a href="#screenshots">Screenshots</a> | <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage">Usage</a></small>
<br/>
<sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub>
<br/><br/>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/8d67382c-e0ce-4286-89f7-7915f09b930c" width="22%" alt="cli init screenshot" align="top">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/dad2bc51-e7e5-484e-bb26-f956ed692d16" width="22%" alt="cli init screenshot" align="top">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/e8e0b6f8-8fdf-4b7f-8124-c10d8699bdb2" width="22%" alt="server snapshot admin screenshot" align="top">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ace0954a-ddac-4520-9d18-1c77b1ec50b2" width="28.6%" alt="server snapshot details page screenshot" align="top"/>
<br/><br/>
</div>

## Key Features

- [**Free & open source**](https://github.com/ArchiveBox/ArchiveBox/blob/dev/LICENSE), own your own data & maintain your privacy by self-hosting
- [**Powerful CLI**](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#CLI-Usage) with [modular dependencies](#dependencies) and [support for Google Drive/NFS/SMB/S3/B2/etc.](https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-Up-Storage)
- [**Comprehensive documentation**](https://github.com/ArchiveBox/ArchiveBox/wiki), [active development](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap), and [rich community](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community)
- [**Extracts a wide variety of content out-of-the-box**](https://github.com/ArchiveBox/ArchiveBox/issues/51): [media (yt-dlp), articles (readability), code (git), etc.](#output-formats)
- [**Supports scheduled/realtime importing**](https://github.com/ArchiveBox/ArchiveBox/wiki/Scheduled-Archiving) from [many types of sources](#input-formats)
- [**Uses standard, durable, long-term formats**](#output-formats) like HTML, JSON, PDF, PNG, MP4, TXT, and WARC
- [**Usable as a oneshot CLI**](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#CLI-Usage), [**self-hosted web UI**](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#UI-Usage), [Python API](https://docs.archivebox.io/en/latest/modules.html) (BETA), [REST API](https://github.com/ArchiveBox/ArchiveBox/issues/496) (ALPHA), or [desktop app](https://github.com/ArchiveBox/electron-archivebox)
- [**Saves all pages to archive.org as well**](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#save_archive_dot_org) by default for redundancy (can be [disabled](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#stealth-mode) for local-only mode)
- Advanced users: support for archiving [content requiring login/paywall/cookies](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#chrome_user_data_dir) (see wiki security caveats!)
- Planned: support for running [JS during archiving](https://github.com/ArchiveBox/ArchiveBox/issues/51) to adblock, [autoscroll](https://github.com/ArchiveBox/ArchiveBox/issues/80), [modal-hide](https://github.com/ArchiveBox/ArchiveBox/issues/175), [thread-expand](https://github.com/ArchiveBox/ArchiveBox/issues/345)

<br/>

## 🤝 Professional Integration

ArchiveBox is free for everyone to self-host, but we also provide support, security review, and custom integrations to help NGOs, governments, and other organizations [run ArchiveBox professionally](https://zulip.archivebox.io/#narrow/stream/167-enterprise/topic/welcome/near/1191102):

- **Journalists:**
  `crawling during research`, `preserving cited pages`, `fact-checking & review`  
- **Lawyers:**
  `collecting & preserving evidence`, `detecting changes`, `tagging & review`  
- **Researchers:**
  `analyzing social media trends`, `getting LLM training data`, `crawling pipelines`
- **Individuals:**
  `saving bookmarks`, `preserving portfolio content`, `legacy / memoirs archival`
- **Governments:**
  `snapshoting public service sites`, `recordkeeping compliance`

> ***[Contact us](https://zulip.archivebox.io/#narrow/stream/167-enterprise/topic/welcome/near/1191102)** if your org wants help using ArchiveBox professionally.*  (we are also seeking [grant funding](https://github.com/ArchiveBox/ArchiveBox/issues/1126#issuecomment-1487431394))  
> We offer: setup & support, CAPTCHA/ratelimit unblocking, SSO, audit logging/chain-of-custody, and more  
> *ArchiveBox is a 🏛️ 501(c)(3) [nonprofit FSP](https://hackclub.com/hcb/) and all our work supports open-source development.* 

<br/>

<div align="center" style="text-align: center">
<br/>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/0db52ea7-4a2c-441d-b47f-5553a5d8fe96" width="49%" alt="grass"/><img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/0db52ea7-4a2c-441d-b47f-5553a5d8fe96" width="49%" alt="grass"/>
</div>

<a name="install"></a>

# Quickstart

**🖥&nbsp; [Supported OSs](https://github.com/ArchiveBox/ArchiveBox/wiki/Install#supported-systems):** Linux/BSD, macOS, Windows (Docker) &nbsp; **👾&nbsp; CPUs:** `amd64` (`x86_64`), `arm64`, `arm7` <sup>(raspi>=3)</sup><br/>

<br/>

#### ✳️&nbsp; Easy Setup

<details>
<summary><b><img src="https://user-images.githubusercontent.com/511499/117447182-29758200-af0b-11eb-97bd-58723fee62ab.png" alt="Docker" height="28px" align="top"/> <code>docker-compose</code></b>  (macOS/Linux/Windows) &nbsp; <b>👈&nbsp; recommended</b> &nbsp; <i>(click to expand)</i></summary>
<br/>
<i>👍 Docker Compose is recommended for the easiest install/update UX + best security + all <a href="#dependencies">extras</a> out-of-the-box.</i>
<br/><br/>
<ol>
<li>Install <a href="https://docs.docker.com/get-docker/">Docker</a> on your system (if not already installed).</li>
<li>Download the <a href="https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/dev/docker-compose.yml" download><code>docker-compose.yml</code></a> file into a new empty directory (can be anywhere).
<pre lang="bash"><code style="white-space: pre-line">mkdir -p ~/archivebox/data && cd ~/archivebox
# Read and edit docker-compose.yml options as-needed after downloading
curl -fsSL 'https://docker-compose.archivebox.io' > docker-compose.yml
</code></pre></li>
<li>Run the initial setup to create an admin user (or set ADMIN_USER/PASS in docker-compose.yml)
<pre lang="bash"><code style="white-space: pre-line">docker compose run archivebox init --setup
</code></pre></li>
<li>Next steps: Start the server then login to the Web UI <a href="http://127.0.0.1:8000">http://127.0.0.1:8000</a> ⇢ Admin.
<pre lang="bash"><code style="white-space: pre-line">docker compose up
# completely optional, CLI can always be used without running a server
# docker compose run [-T] archivebox [subcommand] [--help]
docker compose run archivebox add 'https://example.com'
docker compose run archivebox help
</code></pre>
<i>For more info, see <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Install#option-a-docker--docker-compose-setup-%EF%B8%8F">Install: Docker Compose</a> in the Wiki. ➡️</i>
</li>
</ol>

See <a href="#%EF%B8%8F-cli-usage">below</a> for more usage examples using the CLI, Web UI, or <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#sql-shell-usage">filesystem/SQL/Python</a> to manage your archive.
<br/><br/>
</details>

<details>
<summary><b><img src="https://user-images.githubusercontent.com/511499/117447182-29758200-af0b-11eb-97bd-58723fee62ab.png" alt="Docker" height="28px" align="top"/> <code>docker run</code></b>  (macOS/Linux/Windows)</summary>
<br/>
<ol>
<li>Install <a href="https://docs.docker.com/get-docker/">Docker</a> on your system (if not already installed).</li>
<li>Create a new empty directory and initialize your collection (can be anywhere).
<pre lang="bash"><code style="white-space: pre-line">mkdir -p ~/archivebox/data && cd ~/archivebox/data
docker run -v $PWD:/data -it archivebox/archivebox init --setup
</code></pre>
</li>
<li>Optional: Start the server then login to the Web UI <a href="http://127.0.0.1:8000">http://127.0.0.1:8000</a> ⇢ Admin.
<pre lang="bash"><code style="white-space: pre-line">docker run -v $PWD:/data -p 8000:8000 archivebox/archivebox
# completely optional, CLI can always be used without running a server
# docker run -v $PWD:/data -it [subcommand] [--help]
docker run -v $PWD:/data -it archivebox/archivebox help
</code></pre>
<i>For more info, see <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Install#option-a-docker--docker-compose-setup-%EF%B8%8F">Install: Docker Compose</a> in the Wiki. ➡️</i>
</li>
</ol>

See <a href="#%EF%B8%8F-cli-usage">below</a> for more usage examples using the CLI, Web UI, or filesystem/SQL/Python to manage your archive.
<br/><br/>
</details>

<details>
<summary><b><img src="https://user-images.githubusercontent.com/511499/117456282-08665e80-af16-11eb-91a1-8102eff54091.png" alt="curl sh automatic setup script" height="28px" align="top"/> <code>bash</code> auto-setup script</b>  (macOS/Linux)</summary>
<br/>
<ol>
<li>Install <a href="https://docs.docker.com/get-docker/">Docker</a> on your system (optional, highly recommended but not required).</li>
<li>Run the automatic setup script.
<pre lang="bash"><code style="white-space: pre-line">curl -fsSL 'https://get.archivebox.io' | sh</code></pre>
<i>For more info, see <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Install#option-b-automatic-setup-script">Install: Bare Metal</a> in the Wiki. ➡️</i>
</li>
</ol>

See <a href="#%EF%B8%8F-cli-usage">below</a> for more usage examples using the CLI, Web UI, or filesystem/SQL/Python to manage your archive.<br/>
See <a href="https://github.com/ArchiveBox/ArchiveBox/blob/dev/bin/setup.sh"><code>setup.sh</code></a> for the source code of the auto-install script.<br/>
See <a href="https://docs.sweeting.me/s/against-curl-sh">"Against curl | sh as an install method"</a> blog post for my thoughts on the shortcomings of this install method.
<br/><br/>
</details>

<br/>

#### 🛠&nbsp; Package Manager Setup

<a name="Manual-Setup"></a>


<details>
<summary><b><img src="https://user-images.githubusercontent.com/511499/117447613-ba4c5d80-af0b-11eb-8f89-1d98e31b6a79.png" alt="Pip" height="28px" align="top"/> <code>pip</code></b> (macOS/Linux/BSD)</summary>
<br/>
<ol>

<li>Install <a href="https://realpython.com/installing-python/">Python >= v3.10</a> and <a href="https://nodejs.org/en/download/package-manager/">Node >= v18</a> on your system (if not already installed).</li>
<li>Install the ArchiveBox package using <code>pip3</code> (or <a href="https://pipx.pypa.io"><code>pipx</code></a>).
<pre lang="bash"><code style="white-space: pre-line">pip3 install --upgrade archivebox yt-dlp playwright
playwright install --with-deps chromium
archivebox version
# install any missing extras shown using apt/brew/pkg/etc. see Wiki for instructions
#    python@3.10 node curl wget git ripgrep ...
</code></pre>
<i>See the <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Install">Install: Bare Metal</a> Wiki for full install instructions for each OS...</i>
</li>
<li>Create a new empty directory and initialize your collection (can be anywhere).
<pre lang="bash"><code style="white-space: pre-line">mkdir -p ~/archivebox/data && cd ~/archivebox/data   # for example
archivebox init --setup   # instantialize a new collection
# (--setup auto-installs and link JS dependencies: singlefile, readability, mercury, etc.)
</code></pre>
</li>
<li>Optional: Start the server then login to the Web UI <a href="http://127.0.0.1:8000">http://127.0.0.1:8000</a> ⇢ Admin.
<pre lang="bash"><code style="white-space: pre-line">archivebox server 0.0.0.0:8000
# completely optional, CLI can always be used without running a server
# archivebox [subcommand] [--help]
archivebox help
</code></pre>
</li>
</ol>

See <a href="#%EF%B8%8F-cli-usage">below</a> for more usage examples using the CLI, Web UI, or filesystem/SQL/Python to manage your archive.<br/>
<br/>
<sub>See the <a href="https://github.com/ArchiveBox/pip-archivebox"><code>pip-archivebox</code></a> repo for more details about this distribution.</sub>
<br/><br/>
</details>


<details>
<summary><b><img src="https://user-images.githubusercontent.com/511499/117448075-49597580-af0c-11eb-91ba-f34fff10096b.png" alt="aptitude" height="28px" align="top"/> <code>apt</code></b> (Ubuntu/Debian/etc.)</summary>
<br/>
See the <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Install#option-c-bare-metal-setup">Install: Bare Metal</a> Wiki for instructions. ➡️
<!--<ol>
<li>Add the ArchiveBox repository to your sources.<br/>
<pre lang="bash"><code style="white-space: pre-line">echo "deb http://ppa.launchpad.net/archivebox/archivebox/ubuntu focal main" | sudo tee /etc/apt/sources.list.d/archivebox.list
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys C258F79DCC02E369
sudo apt update
</code></pre>
</li>
<li>Install the ArchiveBox package using <code>apt</code>.
<pre lang="bash"><code style="white-space: pre-line">sudo apt install archivebox
# update to newest version with pip (sometimes apt package is outdated)
pip install --upgrade --ignore-installed archivebox yt-dlp playwright
playwright install --with-deps chromium    # install chromium and its system dependencies
archivebox version                         # make sure all dependencies are installed
</code></pre>
</li>
<li>Create a new empty directory and initialize your collection (can be anywhere).
<pre lang="bash"><code style="white-space: pre-line">mkdir -p ~/archivebox/data && cd ~/archivebox/data
archivebox init --setup
</code></pre>
<br/>
</li>
<li>Optional: Start the server then login to the Web UI <a href="http://127.0.0.1:8000">http://127.0.0.1:8000</a> ⇢ Admin.
<pre lang="bash"><code style="white-space: pre-line">archivebox server 0.0.0.0:8000
# completely optional, CLI can always be used without running a server
# archivebox [subcommand] [--help]
archivebox help
</code></pre>
</li>
</ol>
See <a href="#%EF%B8%8F-cli-usage">below</a> for more usage examples using the CLI, Web UI, or filesystem/SQL/Python to manage your archive.<br/>
<sub>See the <a href="https://github.com/ArchiveBox/debian-archivebox"><code>debian-archivebox</code></a> repo for more details about this distribution.</sub>-->
<br/><br/>
</details>

<details>
<summary><b><img src="https://user-images.githubusercontent.com/511499/117447803-f2ec3700-af0b-11eb-87d3-671d114f011d.png" alt="homebrew" height="28px" align="top"/> <code>brew</code></b> (macOS only)</summary>
<br/>
<ol>
<li>Install <a href="https://brew.sh/#install">Homebrew</a> on your system (if not already installed).</li>
<li>Install the ArchiveBox package using <code>brew</code>.
<pre lang="bash"><code style="white-space: pre-line">brew tap archivebox/archivebox
brew install archivebox
# update to newest version with pip (sometimes brew package is outdated)
pip install --upgrade --ignore-installed archivebox yt-dlp playwright
playwright install --with-deps chromium    # install chromium and its system dependencies
archivebox version                         # make sure all dependencies are installed
</code></pre>
<i>See the <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Install#option-c-bare-metal-setup">Install: Bare Metal</a> Wiki for more granular instructions for macOS... ➡️</i>
</li>
<li>Create a new empty directory and initialize your collection (can be anywhere).
<pre lang="bash"><code style="white-space: pre-line">mkdir -p ~/archivebox/data && cd ~/archivebox/data
archivebox init --setup
</code></pre>
</li>
<li>Optional: Start the server then login to the Web UI <a href="http://127.0.0.1:8000">http://127.0.0.1:8000</a> ⇢ Admin.
<pre lang="bash"><code style="white-space: pre-line">archivebox server 0.0.0.0:8000
# completely optional, CLI can always be used without running a server
# archivebox [subcommand] [--help]
archivebox help
</code></pre><br/>
</li>
</ol>

See <a href="#%EF%B8%8F-cli-usage">below</a> for more usage examples using the CLI, Web UI, or filesystem/SQL/Python to manage your archive.<br/>
<sub>See the <a href="https://github.com/ArchiveBox/homebrew-archivebox"><code>homebrew-archivebox</code></a> repo for more details about this distribution.</sub>
<br/><br/>
</details>

<details>
<summary><img src="https://user-images.githubusercontent.com/511499/118077361-f0616580-b381-11eb-973c-ee894a3349fb.png" alt="Arch" height="28px" align="top"/> <code>pacman</code> / <img src="https://user-images.githubusercontent.com/511499/118077946-29e6a080-b383-11eb-94f0-d4871da08c3f.png" alt="FreeBSD" height="28px" align="top"/> <code>pkg</code> / <img src="https://user-images.githubusercontent.com/511499/118077861-002d7980-b383-11eb-86a7-5936fad9190f.png" alt="Nix" height="28px" align="top"/> <code>nix</code> (Arch/FreeBSD/NixOS/more)</summary>
<br/>

> *Warning: These are contributed by external volunteers and may lag behind the official `pip` channel.*

<ul>
<li>Arch: <a href="https://aur.archlinux.org/packages/archivebox/"><code>yay -S archivebox</code></a> (contributed by <a href="https://github.com/imlonghao"><code>@imlonghao</code></a>)</li>
<li>FreeBSD: <a href="https://github.com/ArchiveBox/ArchiveBox#%EF%B8%8F-easy-setup"><code>curl -fsSL 'https://get.archivebox.io' | sh</code></a> (uses <code>pkg</code> + <code>pip3</code> under-the-hood)</li>
<li>Nix: <a href="https://github.com/NixOS/nixpkgs/blob/master/pkgs/applications/misc/archivebox/default.nix"><code>nix-env --install archivebox</code></a> (contributed by <a href="https://github.com/siraben"><code>@siraben</code></a>)</li>
<li>Guix: <a href="https://packages.guix.gnu.org/packages/archivebox/"><code>guix install archivebox</code></a> (contributed by <a href="https://github.com/rakino"><code>@rakino</code></a>)</li>
<li>More: <a href="https://github.com/ArchiveBox/ArchiveBox/issues/new"><i>contribute another distribution...!</i></a></li>
</ul>
See <a href="#%EF%B8%8F-cli-usage">below</a> for usage examples using the CLI, Web UI, or filesystem/SQL/Python to manage your archive.
<br/><br/>
</details>

<br/>

#### 🎗&nbsp; Other Options

<details>
<summary><b><img src="https://user-images.githubusercontent.com/511499/117447182-29758200-af0b-11eb-97bd-58723fee62ab.png" alt="Docker" height="28px" align="top"/> <code>docker</code> + <img src="https://user-images.githubusercontent.com/511499/117447263-4316c980-af0b-11eb-928d-eaf1292ac646.png" alt="Electron" height="28px" align="top"/> <code>electron</code> Desktop App</b> (macOS/Linux/Windows)</summary>
<br/>
<ol>
<li>Install <a href="https://docs.docker.com/get-docker/">Docker</a> on your system (if not already installed).</li>
<li>Download a binary release for your OS or build the native app from source<br/>
<ul>
<li>macOS: <a href="https://github.com/ArchiveBox/ArchiveBox/releases/download/v0.6.2/Electron-ArchiveBox-macOS-x64-0.6.2.app.zip" download><code>ArchiveBox.app.zip</code></a></li>
<li>Linux: <code>ArchiveBox.deb</code> (alpha: <a href="https://github.com/ArchiveBox/electron-archivebox#quickstart">build manually</a>)</li>
<li>Windows: <code>ArchiveBox.exe</code> (beta: <a href="https://github.com/ArchiveBox/electron-archivebox#quickstart">build manually</a>)</li>
</ul>
</li>
</ol>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/575ef92f-bb3e-4a7c-a4ba-986c1fd76ecf" width="320px">
<br/>
<i>✨ Alpha (contributors wanted!)</i>: for more info, see the: <a href="https://github.com/ArchiveBox/electron-archivebox">Electron ArchiveBox</a> repo.
<br/>
</details>

<details>
<summary><img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/0c46e949-00fe-49c8-a613-ee14501c014c" alt="Self-hosting Platforms" height="28px" align="top"/><b> TrueNAS / UNRAID / YunoHost / Cloudron / etc.</b> (self-hosting solutions)</summary>
<br/>

> *Warning: These are contributed by external volunteers and may lag behind the official `pip` channel.*

<ul>
<li><s>TrueNAS: <a href="https://truecharts.org/charts/stable/archivebox/">Official ArchiveBox TrueChart</a> / <a href="https://dev.to/finloop/setting-up-archivebox-on-truenas-scale-1788">Custom App Guide</a></s> (<a href="https://truecharts.org/news/scale-deprecation/">TrueCharts is discontinued</a>, wait for <a href="https://forums.truenas.com/t/the-future-of-electric-eel-and-apps/5409/">Electric Eel</a>)</li>
<li><a href="https://unraid.net/community/apps?q=archivebox#r">UnRaid</a></li>
<li><a href="https://github.com/YunoHost-Apps/archivebox_ynh">Yunohost</a></li>
<li><a href="https://www.cloudron.io/store/io.archivebox.cloudronapp.html">Cloudron</a></li>
<li><a href="https://docs.saltbox.dev/sandbox/apps/archivebox/">Saltbox</a></li>
<li><a href="https://portainer-templates.as93.net/archivebox">Portainer</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/pull/922/files#diff-00f0606e18b2618c3cc1667ca7c2b703b537af690ca71eba1330633587dcb1ee">AppImage</a></li>
<li><a href="https://runtipi.io/docs/apps-available#:~:text=for%20AI%20Chats.-,ArchiveBox,Open%20source%20self%2Dhosted%20web%20archiving.,-Atuin%20Server">Runtipi</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/issues/986">Umbrel</a> (need contributors...)</li>

<li>More: <a href="https://github.com/ArchiveBox/ArchiveBox/issues/new"><i>contribute another distribution...!</i></a></li>
</ul>
See <a href="#%EF%B8%8F-cli-usage">below</a> for usage examples using the CLI, Web UI, or filesystem/SQL/Python to manage your archive.
<br/><br/>
</details>

<details>
<summary><img src="https://user-images.githubusercontent.com/511499/117448723-1663b180-af0d-11eb-837f-d43959227810.png" alt="paid" height="27px" align="top"/> Paid hosting solutions (cloud VPS)</summary>
<br/>
<ul>
<li><a href="https://zulip.archivebox.io/#narrow/stream/167-enterprise/topic/welcome/near/1191102">
 <img src="https://img.shields.io/badge/Custom_Development-ArchiveBox.io-%231a1a1a.svg?style=flat" height="22px"/>
</a> (<a href="https://zulip.archivebox.io/#narrow/stream/167-enterprise/topic/welcome/near/1191102">get hosting, support, and feature customization directy from us</a>)</li>
<li><a href="https://monadical.com">
 <img src="https://img.shields.io/badge/General_Dev_Consulting-Monadical.com-%231a1a1a.svg?style=flat" height="22px"/>
</a> (<a href="https://monadical.com/contact-us.html">generalist consultancy that has ArchiveBox experience</a>)</li>
<br/>
Other providers of paid ArchiveBox hosting (not officially endorsed):<br/>
<br/><br/>
<li><a href="https://elest.io/open-source/archivebox"><img src="https://img.shields.io/badge/Managed_Hosting-Elest.io-%23193f7e.svg?style=flat" height="22px"/></a></li>
<li><a href="https://www.stellarhosted.com/archivebox/"><img src="https://img.shields.io/badge/Semi_Managed_Hosting-StellarHosted.com-%23193f7e.svg?style=flat" height="22px"/></a> (USD $29-250/mo, <a href="https://www.stellarhosted.com/archivebox/#pricing">pricing</a>)</li>
<li><a href="https://www.pikapods.com/pods?run=archivebox"><img src="https://img.shields.io/badge/Semi_Managed_Hosting-PikaPods.com-%2343a047.svg?style=flat" height="22px"/></a> (from USD $2.6/mo)</li>
<li><a href="https://m.do.co/c/cbc4c0c17840">
 <img src="https://img.shields.io/badge/Unmanaged_VPS-DigitalOcean.com-%232f7cf7.svg?style=flat" height="22px"/>
</a> (USD $5-50+/mo, <a href="https://m.do.co/c/cbc4c0c17840">🎗&nbsp; referral link</a>, <a href="https://www.digitalocean.com/community/tutorials/how-to-install-and-use-docker-compose-on-ubuntu-20-04">instructions</a>)</li>
<li><a href="https://www.vultr.com/?ref=7130289">
 <img src="https://img.shields.io/badge/Unmanaged_VPS-Vultr.com-%232337a8.svg?style=flat" height="22px"/>
</a> (USD $2.5-50+/mo, <a href="https://www.vultr.com/?ref=7130289">🎗&nbsp; referral link</a>, <a href="https://www.vultr.com/docs/install-docker-compose-on-ubuntu-20-04">instructions</a>)</li>
<li><a href="https://fly.io/">
 <img src="https://img.shields.io/badge/Unmanaged_App-Fly.io-%239a2de6.svg?style=flat" height="22px"/>
</a> (USD $10-50+/mo, <a href="https://fly.io/docs/hands-on/start/">instructions</a>)</li>
<li><a href="https://railway.app/template/2Vvhmy">
 <img src="https://img.shields.io/badge/Unmanaged_App-Railway-%23A11BE6.svg?style=flat" height="22px"/>
</a> (USD $0-5+/mo)</li>
<li><a href="https://aws.amazon.com/marketplace/pp/Linnovate-Open-Source-Innovation-Support-For-Archi/B08RVW6MJ2"><img src="https://img.shields.io/badge/Unmanaged_VPS-AWS-%23ee8135.svg?style=flat" height="22px"/></a> (USD $60-200+/mo)</li>
<li><a href="https://azuremarketplace.microsoft.com/en-us/marketplace/apps/meanio.archivebox?ocid=gtmrewards_whatsnewblog_archivebox_vol118"><img src="https://img.shields.io/badge/Unmanaged_VPS-Azure-%237cb300.svg?style=flat" height="22px"/></a> (USD $60-200+/mo)</li>
<br/>
<sub><i>Referral links marked 🎗 provide $5-10 of free credit for new users and help pay for our <a href="https://demo.archivebox.io">demo server</a> hosting costs.</i></sub>
</ul>

For more discussion on managed and paid hosting options see here: <a href="https://github.com/ArchiveBox/ArchiveBox/issues/531">Issue #531</a>.

</details>

<br/>

#### ➡️&nbsp; Next Steps

- Import URLs from some of the supported [Input Formats](#input-formats) or view the supported [Output Formats](#output-formats)...
- Tweak your UI or archiving behavior [Configuration](#configuration), read about some of the [Caveats](#caveats), or [Troubleshoot](https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting)
- Read about the [Dependencies](#dependencies) used for archiving, the [Upgrading Process](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives), or the [Archive Layout](#archive-layout) on disk...
- Or check out our full [Documentation](#documentation) or [Community Wiki](#internet-archiving-ecosystem)...

<br/>

### Usage

#### ⚡️&nbsp; <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#cli-usage">CLI Usage</a>

ArchiveBox commands can be run in a terminal [directly on your host](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#cli-usage), or via [Docker](https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#usage-1)/[Docker Compose](https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#usage).  
<sup>(depending on how you chose to install it above)</sup>

```bash
mkdir -p ~/archivebox/data   # create a new data dir anywhere
cd ~/archivebox/data         # IMPORTANT: cd into the directory

# archivebox [subcommand] [--help]
archivebox version
archivebox help

# equivalent: docker compose run archivebox [subcommand] [--help]
docker compose run archivebox help

# equivalent: docker run -it -v $PWD:/data archivebox/archivebox [subcommand] [--help]
docker run -it -v $PWD:/data archivebox/archivebox help
```

#### ArchiveBox Subcommands

- `archivebox` `help`/`version` to see the list of available subcommands / currently installed version info
- `archivebox` `setup`/`init`/`config`/`status`/`shell`/`manage` to administer your collection
- `archivebox` `add`/`oneshot`/`schedule` to pull in fresh URLs from [bookmarks/history/RSS/etc.](#input-formats)
- `archivebox` `list`/`update`/`remove` to manage existing Snapshots in your collection

<br/>
<details>
<summary><img src="https://user-images.githubusercontent.com/511499/117456282-08665e80-af16-11eb-91a1-8102eff54091.png" alt="curl sh automatic setup script" height="22px" align="top"/> <b>CLI Usage Examples: non-Docker</b></summary>
<br/>
<pre lang="bash"><code style="white-space: pre-line">
# make sure you have pip-installed ArchiveBox and it's available in your $PATH first  
<br/>
# archivebox [subcommand] [--help]
archivebox init --setup      # safe to run init multiple times (also how you update versions)
archivebox version           # get archivebox version info + check dependencies
archivebox help              # get list of archivebox subcommands that can be run
archivebox add --depth=1 'https://news.ycombinator.com'
</code></pre>
<i>For more info, see our <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#cli-usage">Usage: CLI Usage</a> wiki. ➡️</i>
</details>

<br/>

<details>
<summary><img src="https://user-images.githubusercontent.com/511499/117447182-29758200-af0b-11eb-97bd-58723fee62ab.png" alt="Docker" height="22px" align="top"/> <b>CLI Usage Examples: Docker Compose</b></summary>
<br/>
<pre lang="bash"><code style="white-space: pre-line">
# make sure you have `docker-compose.yml` from the Quickstart instructions first
<br/>
# docker compose run archivebox [subcommand] [--help]
docker compose run archivebox init --setup
docker compose run archivebox version
docker compose run archivebox help
docker compose run archivebox add --depth=1 'https://news.ycombinator.com'
# to start webserver: docker compose up
</code></pre>
<i>For more info, see our <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#usage">Usage: Docker Compose CLI</a> wiki. ➡️</i>
</details>

<br/>

<details>
<summary><img src="https://user-images.githubusercontent.com/511499/117447182-29758200-af0b-11eb-97bd-58723fee62ab.png" alt="Docker" height="22px" align="top"/> <b>CLI Usage Examples: Docker</b></summary>
<br/>
<pre lang="bash"><code style="white-space: pre-line">
# make sure you create and cd into in a new empty directory first  
<br/>
# docker run -it -v $PWD:/data archivebox/archivebox [subcommand] [--help]
docker run -v $PWD:/data -it archivebox/archivebox init --setup
docker run -v $PWD:/data -it archivebox/archivebox version
docker run -v $PWD:/data -it archivebox/archivebox help
docker run -v $PWD:/data -it archivebox/archivebox add --depth=1 'https://news.ycombinator.com'
# to start webserver: docker run -v $PWD:/data -it -p 8000:8000 archivebox/archivebox
</code></pre>
<i>For more info, see our <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#usage-1">Usage: Docker CLI</a> wiki. ➡️</i>
</details>

<br/>

<details>
<summary><b>🗄&nbsp; SQL/Python/Filesystem Usage</b></summary>
<pre lang="bash"><code style="white-space: pre-line">
archivebox shell           # explore the Python library API in a REPL
sqlite3 ./index.sqlite3    # run SQL queries directly on your index
ls ./archive/*/index.html  # or inspect snapshot data directly on the filesystem
</code></pre>
<i>For more info, see our <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#python-shell-usage">Python Shell</a>, <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#sql-shell-usage">SQL API</a>, and <a href="https://github.com/ArchiveBox/ArchiveBox#archive-layout">Disk Layout</a> wikis. ➡️</i>
</details>


<br/>

<details>
<summary><b>🖥&nbsp; Web UI & API Usage</b></summary>
<pre lang="bash"><code style="white-space: pre-line">
# Start the server on bare metal (pip/apt/brew/etc):
archivebox manage createsuperuser              # create a new admin user via CLI
archivebox server 0.0.0.0:8000                 # start the server
<br/>
# Or with Docker Compose:
nano docker-compose.yml                        # setup initial ADMIN_USERNAME & ADMIN_PASSWORD
docker compose up                              # start the server
<br/>
# Or with a Docker container:
docker run -v $PWD:/data -it archivebox/archivebox archivebox manage createsuperuser
docker run -v $PWD:/data -it -p 8000:8000 archivebox/archivebox
</code></pre>

<sup>Open <a href="http://localhost:8000"><code>http://localhost:8000</code></a> to see your server's Web UI ➡️</sup>
<br/><br/>
<i>For more info, see our <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#ui-usage">Usage: Web UI</a> wiki. ➡️</i>
<br/><br/>
<b>Optional: Change permissions to allow non-logged-in users</b>

<pre lang="bash"><code style="white-space: pre-line">
archivebox config --set PUBLIC_ADD_VIEW=True   # allow guests to submit URLs 
archivebox config --set PUBLIC_SNAPSHOTS=True  # allow guests to see snapshot content
archivebox config --set PUBLIC_INDEX=True      # allow guests to see list of all snapshots
# or
docker compose run archivebox config --set ...

# restart the server to apply any config changes
</code></pre>
</details>

<br/>
<br/>

> [!TIP]
> Whether in Docker or not, ArchiveBox commands work the same way, and can be used to access the same data on-disk.
> For example, you could run the Web UI in Docker Compose, and run one-off commands with `pip`-installed ArchiveBox.

<details>
<summary><i>Expand to show comparison...</i></summary><br/>

<pre lang="bash"><code style="white-space: pre-line">
archivebox add --depth=1 'https://example.com'                     # add a URL with pip-installed archivebox on the host
docker compose run archivebox add --depth=1 'https://example.com'                       # or w/ Docker Compose
docker run -it -v $PWD:/data archivebox/archivebox add --depth=1 'https://example.com'  # or w/ Docker, all equivalent
</code></pre>

<i>For more info, see our <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Docker">Docker</a> wiki. ➡️</i>

</details>


<br/>
<div align="center" style="text-align: center">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/65f82532-18dd-49c5-86f1-02b1f3100e1e" width="49%" alt="grass"/><img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/65f82532-18dd-49c5-86f1-02b1f3100e1e" width="49%" alt="grass"/>
</div>
<br/>

<div align="center" style="text-align: center">
<sub>. . . . . . . . . . . . . . . . . . . . . . . . . . . .</sub>
<br/><br/>
<a href="https://demo.archivebox.io">DEMO: <code>https://demo.archivebox.io</code></a><br/>
<a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage">Usage</a> | <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration">Configuration</a> | <a href="#Caveats">Caveats</a>
<br/>
</div>

<br/>

---

<div align="center" style="text-align: center">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ac1f897a-8baa-4f8b-8ee8-7443611f258b" width="96%" alt="lego"/>
</div>

<br/>

# Overview

<a name="input-formats"></a>

##  Input Formats: How to pass URLs into ArchiveBox for saving


- <img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ff20d251-5347-4b85-ae9b-83037d0ac01e" height="28px"/> <b>From the official <a href="https://github.com/ArchiveBox/archivebox-extension">ArchiveBox Browser Extension</a></b>  
  <i>Provides realtime archiving of browsing history or selected pages from Chrome/Chromium/Firefox browsers.</i>

- <img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/64078483-21d7-4eb1-aa6e-9ad55afe45b8" height="22px"/> From manual imports of URLs from RSS, JSON, CSV, TXT, SQL, HTML, Markdown, etc. files  
  <i>ArchiveBox supports injesting URLs in [any text-based format](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#Import-a-list-of-URLs-from-a-text-file).</i>

- <img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/32b494e6-4de1-4984-8d88-dc02f18e5c34" height="22px"/> From manually exported [browser history](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive) or [browser bookmarks](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive) (in Netscape format)  
  <i>Instructions: <a href="https://support.google.com/chrome/answer/96816?hl=en">Chrome</a>, <a href="https://support.mozilla.org/en-US/kb/export-firefox-bookmarks-to-backup-or-transfer">Firefox</a>, <a href="https://github.com/ArchiveBox/ArchiveBox/assets/511499/24ad068e-0fa6-41f4-a7ff-4c26fc91f71a">Safari</a>, <a href="https://support.microsoft.com/en-us/help/211089/how-to-import-and-export-the-internet-explorer-favorites-folder-to-a-32-bit-version-of-windows">IE</a>, <a href="https://help.opera.com/en/latest/features/#bookmarks:~:text=Click%20the%20import/-,export%20button,-on%20the%20bottom">Opera</a>, <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive">and more...</a></i>

- <img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/4f7bd318-265c-4235-ad25-38be89946b12" height="22px"/> From URLs visited through a [MITM Proxy](https://mitmproxy.org/) with [`archivebox-proxy`](https://github.com/ArchiveBox/archivebox-proxy)  
  <i>Provides [realtime archiving](https://github.com/ArchiveBox/ArchiveBox/issues/577) of all traffic from any device going through the proxy.</i>

- <img src="https://getpocket.com/favicon.ico" height="22px"/> From bookmarking services or social media (e.g. Twitter bookmarks, Reddit saved posts, etc.)  
  <i>Instructions: <a href="https://getpocket.com/export">Pocket</a>, <a href="https://pinboard.in/export/">Pinboard</a>, <a href="https://www.instapaper.com/user">Instapaper</a>, <a href="https://shaarli.readthedocs.io/en/master/Usage/#importexport">Shaarli</a>, <a href="https://www.groovypost.com/howto/howto/export-delicious-bookmarks-xml/">Delicious</a>, <a href="https://github.com/csu/export-saved-reddit">Reddit Saved</a>, <a href="https://doc.wallabag.org/en/user/import/wallabagv2.html">Wallabag</a>, <a href="http://help.unmark.it/import-export">Unmark.it</a>, <a href="https://www.addictivetips.com/web/onetab-save-close-all-chrome-tabs-to-restore-export-or-import/">OneTab</a>, <a href="https://github.com/ArchiveBox/ArchiveBox/issues/648">Firefox Sync</a>, <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive">and more...</a></i>


<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/e1e5bd78-b0b6-45dc-914c-e1046fee4bc4" width="330px" align="right" style="float: right"/>


```bash
# archivebox add --help
archivebox add 'https://example.com/some/page'
archivebox add --parser=generic_rss < ~/Downloads/some_feed.xml
archivebox add --depth=1 'https://news.ycombinator.com#2020-12-12'
echo 'http://example.com' | archivebox add
echo 'any text with <a href="https://example.com">urls</a> in it' | archivebox add

# if using Docker, add -i when piping stdin:
# echo 'https://example.com' | docker run -v $PWD:/data -i archivebox/archivebox add
# if using Docker Compose, add -T when piping stdin / stdout:
# echo 'https://example.com' | docker compose run -T archivebox add
```

See the [Usage: CLI](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#CLI-Usage) page for documentation and examples.

It also includes a built-in scheduled import feature with `archivebox schedule` and browser bookmarklet, so you can pull in URLs from RSS feeds, websites, or the filesystem regularly/on-demand.

<br/>


<a name="output-formats"></a>

## Output Formats: What ArchiveBox saves for each URL

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ace0954a-ddac-4520-9d18-1c77b1ec50b2" width="330px" align="right" style="float: right"/>


For each web page added, ArchiveBox creates a Snapshot folder and preserves its content as ordinary files inside the folder (e.g. HTML, PDF, PNG, JSON, etc.).

It uses all available methods out-of-the-box, but you can disable extractors and fine-tune the [configuration](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration) as-needed.

<br/>
<details>
<summary><i>Expand to see the full list of ways it saves each page...</i></summary>


<code>data/archive/{Snapshot.id}/</code><br/>
<ul>
<li><strong>Index:</strong> <code>index.html</code> &amp; <code>index.json</code> HTML and JSON index files containing metadata and details</li>
<li><strong>Title</strong>, <strong>Favicon</strong>, <strong>Headers</strong> Response headers, site favicon, and parsed site title</li>
<li><strong>SingleFile:</strong> <code>singlefile.html</code> HTML snapshot rendered with headless Chrome using SingleFile</li>
<li><strong>Wget Clone:</strong> <code>example.com/page-name.html</code> wget clone of the site with  <code>warc/TIMESTAMP.gz</code></li>
<li>Chrome Headless <ul>
<li><strong>PDF:</strong> <code>output.pdf</code> Printed PDF of site using headless chrome</li>
<li><strong>Screenshot:</strong> <code>screenshot.png</code> 1440x900 screenshot of site using headless chrome</li>
<li><strong>DOM Dump:</strong> <code>output.html</code> DOM Dump of the HTML after rendering using headless chrome</li>
</ul></li>
<li><strong>Article Text:</strong> <code>article.html/json</code> Article text extraction using Readability &amp; Mercury</li>
<li><strong>Archive.org Permalink:</strong> <code>archive.org.txt</code> A link to the saved site on archive.org</li>
<li><strong>Audio &amp; Video:</strong> <code>media/</code> all audio/video files + playlists, including subtitles &amp; metadata w/ <code>yt-dlp</code></li>
<li><strong>Source Code:</strong> <code>git/</code> clone of any repository found on GitHub, Bitbucket, or GitLab links</li>
<li><em>More coming soon! See the <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap">Roadmap</a>...</em></li>
</ul>
</details>
<br/>

## Configuration

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ea672e6b-4df5-49d8-b550-7f450951fd27" width="330px" align="right" style="float: right"/>

ArchiveBox can be configured via environment variables, by using the `archivebox config` CLI, or by editing `./ArchiveBox.conf`.
<br/>
<details>
<summary><i>Expand to see examples...</i></summary>
<pre lang="bash"><code style="white-space: pre-line">archivebox config                               # view the entire config
archivebox config --get CHROME_BINARY           # view a specific value
<br/>
archivebox config --set CHROME_BINARY=chromium  # persist a config using CLI
# OR
echo CHROME_BINARY=chromium >> ArchiveBox.conf  # persist a config using file
# OR
env CHROME_BINARY=chromium archivebox ...       # run with a one-off config
</code></pre>
<sub>These methods also work the same way when run inside Docker, see the <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Docker#configuration">Docker Configuration</a> wiki page for details.</sub>
</details><br/>

The configuration is documented here: **[Configuration Wiki](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration)**, and loaded here: [`archivebox/config.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/config.py).

<a name="most-common-options-to-tweak"></a>
<details>
<summary><i>Expand to see the most common options to tweak...</i></summary>
<pre lang="bash"><code style="white-space: pre-line">
# e.g. archivebox config --set TIMEOUT=120
# or   docker compose run archivebox config --set TIMEOUT=120
<br/>
TIMEOUT=240                # default: 60    add more seconds on slower networks
CHECK_SSL_VALIDITY=False   # default: True  False = allow saving URLs w/ bad SSL
SAVE_ARCHIVE_DOT_ORG=False # default: True  False = disable Archive.org saving
MAX_MEDIA_SIZE=1500m       # default: 750m  raise/lower youtubedl output size
<br/>
PUBLIC_INDEX=True          # default: True  whether anon users can view index
PUBLIC_SNAPSHOTS=True      # default: True  whether anon users can view pages
PUBLIC_ADD_VIEW=False      # default: False whether anon users can add new URLs
<br/>
CHROME_USER_AGENT="Mozilla/5.0 ..."  # change these to get around bot blocking
WGET_USER_AGENT="Mozilla/5.0 ..."
CURL_USER_AGENT="Mozilla/5.0 ..."
</code></pre>
</details>
<br/>

## Dependencies

To achieve high-fidelity archives in as many situations as possible, ArchiveBox depends on a variety of 3rd-party libraries and tools that specialize in extracting different types of content.

> Under-the-hood, ArchiveBox uses [Django](https://www.djangoproject.com/start/overview/) to power its [Web UI](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#ui-usage), [Django Ninja](https://django-ninja.dev/) for the REST API, and [SQlite](https://www.sqlite.org/locrsf.html) + the filesystem to provide [fast & durable metadata storage](https://www.sqlite.org/locrsf.html) w/ [deterministic upgrades](https://stackoverflow.com/a/39976321/2156113).

ArchiveBox bundles industry-standard tools like [Google Chrome](https://github.com/ArchiveBox/ArchiveBox/wiki/Chromium-Install), [`wget`, `yt-dlp`, `readability`, etc.](#dependencies) internally, and its operation can be [tuned, secured, and extended](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration) as-needed for many different applications.

<br/>
<details>
<summary><i>Expand to learn more about ArchiveBox's internals & dependencies...</i></summary><br/>

<blockquote>
<p><em>TIP: For better security while running ArchiveBox, and to avoid polluting your host system with a bunch of sub-dependencies that you need to keep up-to-date,<strong>it is strongly recommended to use the <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Docker">⭐️ official Docker image</a></strong> which provides everything in an easy container with simple one-liner upgrades.</em></p>
</blockquote>

<ul>
<li>Language: Python <code>&gt;=3.10</code></li>
<li>Backend: <a href="https://www.djangoproject.com/">Django</a> + <a href="https://django-ninja.dev/">Django-Ninja</a> for REST API</li>
<li>Frontend: <a href="https://docs.djangoproject.com/en/5.1/ref/contrib/admin/">Django Admin</a> + Vanilla HTML, CSS, JS</li>
<li>Web Server: <a href="https://www.djangoproject.com/">Django</a> + <a href="https://channels.readthedocs.io/en/latest/"><code>channels</code></a> + <a href="https://github.com/django/daphne/"><code>daphne]</code></a></li>
<li>Database: <a href="https://docs.djangoproject.com/en/5.1/ref/databases/#sqlite-notes">Django ORM</a> saving to <a href="https://www.sqlite.org/mostdeployed.html">SQLite3</a> <code>./data/index.sqlite</code></li>
<li>Job Queue: <a href="https://huey.readthedocs.io/">Huey</a> using <code>./data/queue.sqlite3</code> under <code>supervisord</code></li>
<li>Build/test/lint: <a href="https://github.com/pdm-project/pdm"><code>pdm</code></a> / <code>mypy</code>+<code>pyright</code>+<code>pytest</code> / <code>ruff</code></li>
<li>Subdependencies: <a href="https://github.com/ArchiveBox/pydantic-pkgr"><code>pydantic-pkgr</code></a> installs apt/brew/pip/npm pkgs at runtime (e.g. <code>yt-dlp</code>, <code>singlefile</code>, <code>readability</code>, <code>git</code>)</li>
</ul>


These optional subdependencies used for archiving sites include:

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/62a02155-05d7-4f3e-8de5-75a50a145c4f" alt="archivebox --version CLI output screenshot showing dependencies installed" width="330px" align="right" style="max-width: 100%;">

<ul>
<li><code>chromium</code> / <code>chrome</code> (for screenshots, PDF, DOM HTML, and headless JS scripts)</li>
<li><code>node</code> &amp; <code>npm</code> (for readability, mercury, and singlefile)</li>
<li><code>wget</code> (for plain HTML, static files, and WARC saving)</li>
<li><code>curl</code> (for fetching headers, favicon, and posting to Archive.org)</li>
<li><code>yt-dlp</code> or <code>youtube-dl</code> (for audio, video, and subtitles)</li>
<li><code>git</code> (for cloning git repos)</li>
<li><code>singlefile</code> (for saving into a self-contained html file)</li>
<li><code>postlight/parser</code> (for discussion threads, forums, and articles)</li>
<li><code>readability</code> (for articles and long text content)</li>
<li>and more as we grow...</li>
</ul>

You don't need to install every dependency to use ArchiveBox. ArchiveBox will automatically disable extractors that rely on dependencies that aren't installed, based on what is configured and available in your <code>$PATH</code>.
  
If not using Docker, make sure to keep the dependencies up-to-date yourself and check that ArchiveBox isn't reporting any incompatibility with the versions you install.

<pre lang="bash"><code style="white-space: pre-line">#install python3 and archivebox with your system package manager
# apt/brew/pip/etc install ... (see Quickstart instructions above)
<br/>
which -a archivebox    # see where you have installed archivebox
archivebox setup       # auto install all the extractors and extras
archivebox --version   # see info and check validity of installed dependencies
</code></pre>
  
Installing directly on <strong>Windows without Docker or WSL/WSL2/Cygwin is not officially supported</strong> (I cannot respond to Windows support tickets), but some advanced users have reported getting it working.

<h4>Learn More</h4>
<ul>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Install#dependencies">Wiki: Install (Dependencies)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Chromium-Install">Wiki: Chromium Install</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives">Wiki: Upgrading or Merging Archives</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting#installing">Wiki: Troubleshooting (Installing)</a></li>
</ul>

</details>
<br/>


## Archive Layout

All of ArchiveBox's state (SQLite DB, content, config, logs, etc.) is stored in a single folder per collection.

<br/>
<details>
<summary><i>Expand to learn more about the layout of Archivebox's data on-disk...</i></summary><br/>

Data folders can be created anywhere (`~/archivebox/data` or `$PWD/data` as seen in our examples), and you can create as many data folders as you want to hold different collections.
All <code>archivebox</code> CLI commands are designed to be run from inside an ArchiveBox data folder, starting with <code>archivebox init</code> to initialize a new collection inside an empty directory.

<pre lang="bash"><code style="white-space: pre-line">mkdir -p ~/archivebox/data && cd ~/archivebox/data   # just an example, can be anywhere
archivebox init</code></pre>

The on-disk layout is optimized to be easy to browse by hand and durable long-term. The main index is a standard <code>index.sqlite3</code> database in the root of the data folder (it can also be <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive#2-export-and-host-it-as-static-html">exported as static JSON/HTML</a>), and the archive snapshots are organized by date-added timestamp in the <code>data/archive/</code> subfolder.

<img src="https://user-images.githubusercontent.com/511499/117453293-c7b91600-af12-11eb-8a3f-aa48b0f9da3c.png" width="400px" align="right" style="float: right"/>


<pre lang="bash"><code style="white-space: pre-line">data/
    index.sqlite3
    ArchiveBox.conf
    archive/
        ...
        1617687755/
            index.html
            index.json
            screenshot.png
            media/some_video.mp4
            warc/1617687755.warc.gz
            git/somerepo.git
            ...
</code></pre>

Each snapshot subfolder <code>data/archive/TIMESTAMP/</code> includes a static <code>index.json</code> and <code>index.html</code> describing its contents, and the snapshot extractor outputs are plain files within the folder.

<h4>Learn More</h4>
<ul>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-Up-Storage">Wiki: Setting Up Storage (SMB, NFS, S3, B2, Google Drive, etc.)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#Disk-Layout">Wiki: Usage (Disk Layout)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#large-archives">Wiki: Usage (Large Archives)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#output-folder">Wiki: Security Overview (Output Folder)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive">Wiki: Publishing Your Archive</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives">Wiki: Upgrading or Merging Archives</a></li>
</ul>

</details>
<br/>


## Static Archive Exporting

You can create one-off archives of individual URLs with `archivebox oneshot`, or export your index as static HTML using `archivebox list` (so you can view it without an ArchiveBox server).

<br/>
<details>
<summary><i>Expand to learn how to export your ArchiveBox collection...</i></summary><br/>

<blockquote>
<p><em>NOTE: These exports are not paginated, exporting many URLs or the entire archive at once may be slow. Use the filtering CLI flags on the <code>archivebox list</code> command to export specific Snapshots or ranges.</em></p>
</blockquote>

<pre lang="bash"><code style="white-space: pre-line"># do a one-off single URL archive wihout needing a data dir initialized
archivebox oneshot 'https://example.com'

# archivebox list --help
archivebox list --html --with-headers > index.html     # export to static html table
archivebox list --json --with-headers > index.json     # export to json blob
archivebox list --csv=timestamp,url,title > index.csv  # export to csv spreadsheet

# (if using Docker Compose, add the -T flag when piping)
# docker compose run -T archivebox list --html 'https://example.com' > index.json
</code></pre>

The paths in the static exports are relative, make sure to keep them next to your `./archive` folder when backing them up or viewing them.

<h4>Learn More</h4>

<ul>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive#2-export-and-host-it-as-static-html">Wiki: Publishing Your Archive (Exporting as Static HTML)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#publishing">Wiki: Security Overview (Publishing)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#public_index--public_snapshots--public_add_view">Wiki: Configuration (<code>PUBLIC_INDEX</code>, <code>PUBLIC_SNAPSHOTS</code>, <code>PUBLIC_ADD_VIEW</code>)</a></li>
</ul>

</details>
<br/>


<div align="center" style="text-align: center">
<img src="https://docs.monadical.com/uploads/upload_b6900afc422ae699bfefa2dcda3306f3.png" width="100%" alt="security graphic"/>
</div>


## Caveats

### Archiving Private Content

<a id="archiving-private-urls"></a>

If you're importing pages with private content or URLs containing secret tokens you don't want public (e.g Google Docs, paywalled content, unlisted videos, etc.), **you may want to disable some of the extractor methods to avoid leaking that content to 3rd party APIs or the public**.

<br/>
<details>
<summary><i>Expand to learn about privacy, permissions, and user accounts...</i></summary>


<pre lang="bash"><code style="white-space: pre-line"># don't save private content to ArchiveBox, e.g.:
archivebox add 'https://docs.google.com/document/d/12345somePrivateDocument'
archivebox add 'https://vimeo.com/somePrivateVideo'

# without first disabling saving to Archive.org:
archivebox config --set SAVE_ARCHIVE_DOT_ORG=False  # disable saving all URLs in Archive.org

# restrict the main index, Snapshot content, and Add Page to authenticated users as-needed:
archivebox config --set PUBLIC_INDEX=False
archivebox config --set PUBLIC_SNAPSHOTS=False
archivebox config --set PUBLIC_ADD_VIEW=False 
archivebox manage createsuperuser

# if extra paranoid or anti-Google:
archivebox config --set SAVE_FAVICON=False          # disable favicon fetching (it calls a Google API passing the URL's domain part only)
archivebox config --set CHROME_BINARY=chromium      # ensure it's using Chromium instead of Chrome
</code></pre>

<blockquote>
<p><em>CAUTION: Assume anyone <em>viewing</em> your archives will be able to see any cookies, session tokens, or private URLs passed to ArchiveBox during archiving.</em>
<em>Make sure to secure your ArchiveBox data and don't share snapshots with others without stripping out sensitive headers and content first.</em></p>
</blockquote>

<h4>Learn More</h4>

<ul>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive">Wiki: Publishing Your Archive</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview">Wiki: Security Overview</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Chromium-Install#setting-up-a-chromium-user-profile">Wiki: Chromium Install (Setting Up a User Profile)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#chrome_user_data_dir">Wiki: Configuration (<code>CHROME_USER_DATA_DIR</code>)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#cookies_file">Wiki: Configuration (<code>COOKIES_FILE</code>)</a></li>
</ul>

</details>
<br/>


### Security Risks of Viewing Archived JS

Be aware that malicious archived JS can access the contents of other pages in your archive when viewed. Because the Web UI serves all viewed snapshots from a single domain, they share a request context and **typical CSRF/CORS/XSS/CSP protections do not work to prevent cross-site request attacks**. See the [Security Overview](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#stealth-mode) page and [Issue #239](https://github.com/ArchiveBox/ArchiveBox/issues/239) for more details.


<br/>
<details>
<summary><i>Expand to see risks and mitigations...</i></summary>


<pre lang="bash"><code style="white-space: pre-line"># visiting an archived page with malicious JS:
https://127.0.0.1:8000/archive/1602401954/example.com/index.html

# example.com/index.js can now make a request to read everything from:
https://127.0.0.1:8000/index.html
https://127.0.0.1:8000/archive/*
# then example.com/index.js can send it off to some evil server
</code></pre>

<blockquote>
<p><em>NOTE: Only the <code>wget</code> &amp; <code>dom</code> extractor methods execute archived JS when viewing snapshots, all other archive methods produce static output that does not execute JS on viewing.</em><br/>
<em>If you are worried about these issues ^ you should disable these extractors using:<br/> <code>archivebox config --set SAVE_WGET=False SAVE_DOM=False</code>.</em></p>
</blockquote>

<h4>Learn More</h4>
<ul>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview">Wiki: Security Overview</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/issues/239">ArchiveBox Github Issue: #239</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/security/advisories/GHSA-cr45-98w9-gwqx">Security Advisory: <code>CVE-2023-45815</code></a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#publishing">Wiki: Security Overview (Publishing)</a></li>
</ul>

</details>
<br/>


### Working Around Sites that Block Archiving

For various reasons, many large sites (Reddit, Twitter, Cloudflare, etc.) actively block archiving or bots in general. There are a number of approaches to work around this, and we also provide <a href="https://docs.monadical.com/s/archivebox-consulting-services">consulting services</a> to help here.

<br/>
<details>
<summary><i>Click to learn how to set up user agents, cookies, and site logins...</i></summary>
<br/>


<ul>
<li>Set <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#curl_user_agent"><code>CHROME_USER_AGENT</code>, <code>WGET_USER_AGENT</code>, <code>CURL_USER_AGENT</code></a> to impersonate a real browser (by default, ArchiveBox reveals that it's a bot when using the default user agent settings)</li>
<li>Set up a logged-in browser session for archiving using <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Chromium-Install#setting-up-a-chromium-user-profile"><code>CHROME_USER_DATA_DIR</code> &amp; <code>COOKIES_FILE</code></a></li>
<li>Rewrite your URLs before archiving to swap in alternative frontends that are more bot-friendly e.g.<br>
<code>reddit.com/some/url</code> -&gt; <code>teddit.net/some/url</code>: <a href="https://github.com/mendel5/alternative-front-ends">https://github.com/mendel5/alternative-front-ends</a></li>
</ul>

In the future we plan on adding support for running JS scripts during archiving to block ads, cookie popups, modals, and fix other issues. Follow here for progress: <a href="https://github.com/ArchiveBox/ArchiveBox/issues/51">Issue #51</a>.

</details>
<br/>


### Saving Multiple Snapshots of a Single URL

ArchiveBox appends a hash with the current date `https://example.com#2020-10-24` to differentiate when a single URL is archived multiple times.


<br/>
<details>
<summary><i>Click to learn how the <code>Re-Snapshot</code> feature works...</i></summary>
<br/>


Because ArchiveBox uniquely identifies snapshots by URL, it must use a workaround to take multiple snapshots of the same URL (otherwise they would show up as a single Snapshot entry). It makes the URLs of repeated snapshots unique by adding a hash with the archive date at the end:

<pre lang="bash"><code style="white-space: pre-line">archivebox add 'https://example.com#2020-10-24'
...
archivebox add 'https://example.com#2020-10-25'
</code></pre>

The <img src="https://user-images.githubusercontent.com/511499/115942091-73c02300-a476-11eb-958e-5c1fc04da488.png" alt="Re-Snapshot Button" height="24px"/> button in the Admin UI is a shortcut for this hash-date multi-snapshotting workaround.

Improved support for saving multiple snapshots of a single URL without this hash-date workaround will be <a href="https://github.com/ArchiveBox/ArchiveBox/issues/179">added eventually</a> (along with the ability to view diffs of the changes between runs).

<h4>Learn More</h4>

<ul>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/issues/179">ArchiveBox Issues: #179</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#explanation-of-buttons-in-the-web-ui---admin-snapshots-list">Wiki: Usage (Explanation of Web UI Buttons)</a></li>
</ul>

</details>
<br/>

### Storage Requirements

Because ArchiveBox is designed to ingest a large volume of URLs with multiple copies of each URL stored by different 3rd-party tools, it can be quite disk-space intensive. There are also some special requirements when using filesystems like NFS/SMB/FUSE.

<br/>
<details>
<summary><i>Click to learn more about ArchiveBox's filesystem and hosting requirements...</i></summary>
<br/>

<ul>
<li><strong>ArchiveBox can use anywhere from ~1gb per 1000 Snapshots, to ~50gb per 1000 Snapshots</strong>, mostly dependent on whether you're saving audio & video using <code>SAVE_MEDIA=True</code> and whether you lower <code>MEDIA_MAX_SIZE=750mb</code>.</li>
<li>Disk usage can be reduced by using a compressed/<a href="https://www.ixsystems.com/blog/ixsystems-and-klara-systems-celebrate-valentines-day-with-a-heartfelt-donation-of-fast-dedupe-to-openzfs-and-truenas/">deduplicated</a> filesystem like <a href="https://www.reddit.com/r/zfs/comments/t9cexx/a_simple_real_world_zfs_compression_speed_an/">ZFS</a>/BTRFS, or by turning off extractors methods you don't need. You can also deduplicate content with a tool like <a href="https://github.com/adrianlopezroche/fdupes"><code>fdupes</code></a> or <a href="https://github.com/pauldreik/rdfind"><code>rdfind</code></a>.  
</li>
<li><strong>Don't store large collections on older filesystems like EXT3/FAT</strong> as they may not be able to handle more than 50k directory entries in the <code>data/archive/</code> folder.
</li>
<li><strong>Try to keep the <code>data/index.sqlite3</code> file on local drive (not a network mount)</strong> or SSD for maximum performance, however the <code>data/archive/</code> folder can be on a network mount or slower HDD.</li>
<li>If using Docker or NFS/SMB/FUSE for the <code>data/archive/</code> folder, you may need to set <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#puid--pgid"><code>PUID</code> & <code>PGID</code></a> and <a href="https://github.com/ArchiveBox/ArchiveBox/issues/1304">disable <code>root_squash</code></a> on your fileshare server.
</li>
</ul>

<h4>Learn More</h4>

<ul>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#Disk-Layout">Wiki: Usage (Disk Layout)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#output-folder">Wiki: Security Overview (Output-Folder)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Usage#large-archives">Wiki: Usage (Large Archives)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#puid--pgid">Wiki: Configuration (<code>PUID</code> & <code>GUID</code>)</a></li>
<li><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#do-not-run-as-root">Wiki: Security Overview (Do Not Run as Root)</a></li>
</ul>


</details>
<br/>


---


<br/>


## Screenshots

<div align="center" width="80%">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/0362bcd1-1dfd-43c6-b4ec-db5e78da07b2" width="80%"/>
<table>
<tbody>
<tr>
<td>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/e9fdcb16-344e-48c8-8be0-efa48ec155d5" alt="brew install archivebox" width="210px"><br/>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/e235c9d8-fda9-499d-a6a5-59b0e6a0efce" alt="archivebox version" width="210px">
</td>
<td>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/0e3da0c7-d2c2-4a71-b096-6caedafd6ef7" alt="archivebox init" width="210px"><br/>
</td>
<td>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/31c47440-ec14-4a02-99a3-aae8a9078d46" alt="archivebox add" width="210px">
</td>
<td>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ebcdc21d-e2af-4bf8-ad4b-bc4f3151bbef" alt="archivebox data dir" width="210px">
</td>
</tr>
<tr>
<td>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ea672e6b-4df5-49d8-b550-7f450951fd27" alt="archivebox server" width="210px">
</td>
<td>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/e1e5bd78-b0b6-45dc-914c-e1046fee4bc4" alt="archivebox server add" width="210px">
</td>
<td>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/e8e0b6f8-8fdf-4b7f-8124-c10d8699bdb2" alt="archivebox server list" width="210px">
</td>
<td>
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ace0954a-ddac-4520-9d18-1c77b1ec50b2" alt="archivebox server detail" width="210px">
</td>
</tr>
</tbody>
</table>
</div>
<br/>

<br/>
<div align="center" style="text-align: center">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ca85432e-a2df-40c6-968f-51a1ef99b24e" width="100%" alt="paisley graphic">
</div>


# Background & Motivation

ArchiveBox aims to enable more of the internet to be saved from deterioration by empowering people to self-host their own archives. The intent is for all the web content you care about to be viewable with common software in 50 - 100 years without needing to run ArchiveBox or other specialized software to replay it.


<br/>
<details>
<summary><i>Click to read more about why archiving is important and how to do it ethically...</i></summary>
<br/>


Vast treasure troves of knowledge are lost every day on the internet to link rot. As a society, we have an imperative to preserve some important parts of that treasure, just like we preserve our books, paintings, and music in physical libraries long after the originals go out of print or fade into obscurity.

Whether it's to resist censorship by saving news articles before they get taken down or edited, or just to save a collection of early 2010's flash games you loved to play, having the tools to archive internet content enables to you save the stuff you care most about before it disappears.

<div align="center" style="text-align: center">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/71e36bc5-1c94-44e2-92b6-405fa898c734" width="40%"/><br/>
<sup><i>Image from <a href="https://perma.cc/">Perma.cc</a>...</i><br/></sup>
</div>

The balance between the permanence and ephemeral nature of content on the internet is part of what makes it beautiful. I don't think everything should be preserved in an automated fashion--making all content permanent and never removable, but I do think people should be able to decide for themselves and effectively archive specific content that they care about, just like libraries do. Without the work of archivists saving physical books, manuscrips, and paintings we wouldn't have any knowledge of our ancestors' history. I believe archiving the web is just as important to provide the same benefit to future generations.

ArchiveBox's stance is that duplication of other people's content is only ethical if it:

- A. doesn't deprive the original creators of revenue and
- B. is responsibly curated by an individual/institution.

In the U.S., <a href="https://guides.library.oregonstate.edu/copyright/libraries">libraries, researchers, and archivists</a> are allowed to duplicate copyrighted materials under <a href="https://libguides.ala.org/copyright/fairuse">"fair use"</a> for <a href="https://guides.cuny.edu/cunyfairuse/librarians#:~:text=One%20of%20these%20specified%20conditions,may%20be%20liable%20for%20copyright">private study, scholarship, or research</a>. Archive.org's non-profit preservation work is <a href="https://blog.archive.org/2024/03/01/fair-use-in-action-at-the-internet-archive/">covered under fair use</a> in the US, and they properly handle <a href="https://cardozoaelj.com/2015/03/20/use-of-copyright-law-to-take-down-revenge-porn/">unethical content</a>/<a href="https://help.archive.org/help/rights/">DMCA</a>/<a href="https://gdpr.eu/right-to-be-forgotten/#:~:text=An%20individual%20has%20the%20right,that%20individual%20withdraws%20their%20consent.">GDPR</a> removal requests to maintain good standing in the eyes of the law.

As long as you A. don't try to profit off pirating copyrighted content and B. have processes in place to respond to removal requests, many countries allow you to use sofware like ArchiveBox to ethically and responsibly archive any web content you can view. That being said, ArchiveBox is not liable for how you choose to operate the software. You must research your own local laws and regulations, and get proper legal council if you plan to host a public instance (start by putting your DMCA/GDPR contact info in <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#footer_info"><code>FOOTER_INFO</code></a> and changing your instance's branding using <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#custom_templates_dir"><code>CUSTOM_TEMPLATES_DIR</code></a>).

</details>
<br/>


## Comparison to Other Projects

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/4cac62a9-e8fb-425b-85a3-ca644aa6dd42" width="5%" align="right" alt="comparison" style="float: right"/> 


> **Check out our [community wiki](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community) for a list of alternative web archiving tools and orgs.**

ArchiveBox gained momentum in the internet archiving industry because it uniquely combines 3 things:

- **it's distributed:** users own their data instead of entrusting it to one big central provider
- **it's future-proof:** saving in *multiple formats* and extracting out raw TXT, PNG, PDF, MP4, etc. files
- **it's extensible:** with powerful APIs, flexible storage, and a big community adding new extractors regularly

<br/>
<details>
<summary><i>Expand for a more direct comparison to Archive.org and specific open-source alternatives...</i></summary><br/>

ArchiveBox tries to be a robust, set-and-forget archiving solution suitable for archiving RSS feeds, bookmarks, or your entire browsing history (beware, it may be too big to store), including private/authenticated content that you wouldn't otherwise share with a centralized service like Archive.org.

<h3>Comparison With Centralized Public Archives</h3>

Not all content is suitable to be archived on a centralized, publicly accessible platform. Archive.org doesn't offer the ability to save things behind login walls for good reason, as the content may not have been intended for a public audience. ArchiveBox exists to fill that gap by letting everyone save what they have access to on an individual basis, and to encourage decentralized archiving that's less succeptible to censorship or natural disasters.

By having users store their content locally or within their organizations, we can also save much larger portions of the internet than a centralized service has the disk capcity handle. The eventual goal is to work towards federated archiving where users can share portions of their collections with each other, and with central archives on a case-by-case basis.

<h3>Comparison With Other Self-Hosted Archiving Options</h3>

ArchiveBox differentiates itself from [similar self-hosted projects](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#Web-Archiving-Projects) by providing both a comprehensive CLI interface for managing your archive, a Web UI that can be used either independently or together with the CLI, and a simple on-disk data format that can be used without either.


*If you want better fidelity for very complex interactive pages with heavy JS/streams/API requests, check out [ArchiveWeb.page](https://archiveweb.page) and [ReplayWeb.page](https://replayweb.page).*

*If you want more bookmark categorization and note-taking features, check out [Archivy](https://archivy.github.io/), [Memex](https://github.com/WorldBrain/Memex), [Polar](https://getpolarized.io/), or [LinkAce](https://www.linkace.org/).*

*If you need more advanced recursive spider/crawling ability beyond `--depth=1`, check out [Browsertrix](https://github.com/webrecorder/browsertrix-crawler), [Photon](https://github.com/s0md3v/Photon), or [Scrapy](https://scrapy.org/) and pipe the outputted URLs into ArchiveBox.*

For more alternatives, see our [list here](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#Web-Archiving-Projects)...

ArchiveBox is neither the highest fidelity nor the simplest tool available for self-hosted archiving, rather it's a jack-of-all-trades that tries to do most things well by default. We encourage you to try these other tools made by our friends if ArchiveBox isn't suited to your needs.

</details>

<br/>

<!--<div align="center" style="text-align: center"><br/><img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/04808ac2-3133-44fd-8703-3387e06dc851" width="100%" alt="dependencies graphic"></div>-->

## Internet Archiving Ecosystem

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/78d8a725-97f4-47f5-b983-1f62843ddc51" width="14%" align="right" style="float: right"/>

<details>
<summary><i>Our <b><a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community">Community Wiki</a></b> strives to be a comprehensive index of the web archiving industry...</i></summary>
<br/>

- [Community Wiki](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community)
  - [Web Archiving Software](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#web-archiving-projects)  
    _List of ArchiveBox alternatives and open source projects in the internet archiving space._
  - [Awesome-Web-Archiving Lists](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#the-master-lists)  
    _Community-maintained indexes of archiving tools and institutions like `iipc/awesome-web-archiving`._
  - [Reading List](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#reading-list)  
    _Articles, posts, and blogs relevant to ArchiveBox and web archiving in general._
  - [Communities](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community#communities)  
    _A collection of the most active internet archiving communities and initiatives._
- Check out the ArchiveBox [Roadmap](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap) and [Changelog](https://github.com/ArchiveBox/ArchiveBox/wiki/Changelog)
- Learn why archiving the internet is important by reading the "[On the Importance of Web Archiving](https://items.ssrc.org/parameters/on-the-importance-of-web-archiving/)" blog post.
- Reach out to me for questions and comments via [@ArchiveBoxApp](https://twitter.com/ArchiveBoxApp) or [@theSquashSH](https://twitter.com/thesquashSH) on Twitter

</details>

<br/>

**Need help building a custom archiving solution?**

> ✨ **[Hire the team that built Archivebox](https://zulip.archivebox.io/#narrow/stream/167-enterprise/topic/welcome/near/1191102) to solve archiving for your org.** ([@ArchiveBoxApp](https://twitter.com/ArchiveBoxApp))

<br/>


<div align="center" style="text-align: center">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/897f7a88-1265-4aab-b80c-b1640afaad1f" width="100%" alt="documentation graphic">
</div>

# Documentation

<img src="https://read-the-docs-guidelines.readthedocs-hosted.com/_images/logo-dark.png" width="13%" align="right" style="float: right"/>

We use the [ArchiveBox GitHub Wiki](https://github.com/ArchiveBox/ArchiveBox/wiki) for documentation.

<sub>There is also a mirror available on <a href="https://archivebox.readthedocs.io/en/latest/">Read the Docs</a> (though it's sometimes outdated).</sub>

> ✏️ You can submit docs changes & suggestions in our dedicated repo [`ArchiveBox/docs`](https://github.com/ArchiveBox/docs).

## Getting Started

- [Quickstart](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart)
- [Install](https://github.com/ArchiveBox/ArchiveBox/wiki/Install)
- [Docker](https://github.com/ArchiveBox/ArchiveBox/wiki/Docker)
- [Usage](https://github.com/ArchiveBox/ArchiveBox/wiki/Usage)
- [Configuration](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration)
- [Supported Sources](https://github.com/ArchiveBox/ArchiveBox/wiki/Quickstart#2-get-your-list-of-urls-to-archive)
- [Supported Outputs](https://github.com/ArchiveBox/ArchiveBox/wiki#can-save-these-things-for-each-site)
- [Scheduled Archiving](https://github.com/ArchiveBox/ArchiveBox/wiki/Scheduled-Archiving)

## Advanced

- [Security Overview](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview)
- [Cookies & Sessions Setup](https://github.com/ArchiveBox/ArchiveBox/wiki/Chromium-Install#setting-up-a-chromium-user-profile) (archiving sites that require logins)
- [Setting up the Search Backends](https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-up-Search) (choosing ripgrep, Sonic, or FTS5)
- [Setting up Local/Remote Storages](https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-up-Storage) (S3/B2/Google Drive/SMB/NFS/etc.)
- [Setting up Authentication & Permissions](https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-up-Authentication) (SSO/LDAP/OAuth/API Keys/etc.)
- [Publishing Your Archive](https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive) (sharing your archive server with others)
- [Chromium Install Options](https://github.com/ArchiveBox/ArchiveBox/wiki/Chromium-Install) (installing and configuring ArchiveBox's Chrome)
- [Upgrading or Merging Archives](https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives)
- [Troubleshooting](https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting)

## Developers

- [Developer Documentation](https://github.com/ArchiveBox/ArchiveBox#archivebox-development)
- [Python API](https://docs.archivebox.io/)
- [REST API](https://demo.archivebox.io/api) (alpha)

## More Info

- [Bug Tracker](https://github.com/ArchiveBox/ArchiveBox/issues)
- [Roadmap](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap)
- [Changelog](https://github.com/ArchiveBox/ArchiveBox/releases)
- [Donations](https://github.com/ArchiveBox/ArchiveBox/wiki/Donations)
- [Background & Motivation](https://github.com/ArchiveBox/ArchiveBox#background--motivation)
- [Web Archiving Community](https://github.com/ArchiveBox/ArchiveBox/wiki/Web-Archiving-Community)

<br/>

---

<div align="center" style="text-align: center">
<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/e895e79f-5c7d-429b-ad8a-7df2cc183ca3" width="100%" alt="development">
</div>

# ArchiveBox Development

All contributions to ArchiveBox are welcomed! Check our [issues](https://github.com/ArchiveBox/ArchiveBox/issues) and [Roadmap](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap) for things to work on, and please open an issue to discuss your proposed implementation before working on things! Otherwise we may have to close your PR if it doesn't align with our roadmap.

For low hanging fruit / easy first tickets, see: <a href="https://github.com/ArchiveBox/ArchiveBox/issues?q=is%3Aissue+is%3Aopen+sort%3Aupdated-desc+label%3A%22help+wanted%22">ArchiveBox/Issues `#good first ticket` `#help wanted`</a>.

**Python API Documentation:** https://docs.archivebox.io/en/dev/archivebox.html#module-archivebox.main

### Setup the dev environment

<details><summary><i>Click to expand...</i></summary>

#### 1. Clone the main code repo (making sure to pull the submodules as well)

```bash
git clone --recurse-submodules https://github.com/ArchiveBox/ArchiveBox
cd ArchiveBox
git checkout dev  # or the branch you want to test
git submodule update --init --recursive
git pull --recurse-submodules
```

#### 2. Option A: Install the Python, JS, and system dependencies directly on your machine

```bash
# Install ArchiveBox + python dependencies
pip install uv
uv venv
uv sync

archivebox init
archivebox install
```

#### 2. Option B: Build the docker container and use that for development instead

```bash
# Optional: develop via docker by mounting the code dir into the container
# if you edit e.g. ./archivebox/core/models.py on the docker host, runserver
# inside the container will reload and pick up your changes
docker build . -t archivebox
docker run -it \
    -v $PWD/data:/data \
    archivebox init --setup
docker run -it -p 8000:8000 \
    -v $PWD/data:/data \
    -v $PWD/archivebox:/app/archivebox \
    archivebox server 0.0.0.0:8000 --debug --reload

# (remove the --reload flag and add the --nothreading flag when profiling with the django debug toolbar)
# When using --reload, make sure any files you create can be read by the user in the Docker container, eg with 'chmod a+rX'.
```

</details>

### Common development tasks

See the `./bin/` folder and read the source of the bash scripts within.
You can also run all these in Docker. For more examples see the GitHub Actions CI/CD tests that are run: `.github/workflows/*.yaml`.

#### Run in DEBUG mode

<details><summary><i>Click to expand...</i></summary>

```bash
archivebox config --set DEBUG=True
# or
archivebox server --debug ...
# faster dev version wo/ bg workers enabled:
daphne -b 0.0.0.0 -p 8000 archivebox.core.asgi:application
```

https://stackoverflow.com/questions/1074212/how-can-i-see-the-raw-sql-queries-django-is-running

</details>

#### Install and run a specific GitHub branch

<details><summary><i>Click to expand...</i></summary>

##### Use a Pre-Built Image

If you're looking for the latest `dev` Docker image, it's often available pre-built on Docker Hub, simply pull and use `archivebox/archivebox:dev`.

```bash
docker pull archivebox/archivebox:dev
docker run archivebox/archivebox:dev version
# verify the BUILD_TIME and COMMIT_HASH in the output are recent
```

##### Build Branch from Source
  
You can also build and run any branch yourself from source, for example to build & use `dev` locally:

```bash
# docker-compose.yml:
services:
    archivebox:
        image: archivebox/archivebox:dev
        build: 'https://github.com/ArchiveBox/ArchiveBox.git#dev'
        ...

# or with plain Docker:
docker build -t archivebox:dev https://github.com/ArchiveBox/ArchiveBox.git#dev
docker run -it -v $PWD:/data archivebox:dev init

# or with pip:
pip install 'git+https://github.com/pirate/ArchiveBox@dev'
npm install 'git+https://github.com/ArchiveBox/ArchiveBox.git#dev'
archivebox install
```

</details>

#### Run the linters / tests

<details><summary><i>Click to expand...</i></summary>

```bash
./bin/lint.sh
./bin/test.sh
```
(uses `flake8`, `mypy`, and `pytest -s`)

</details>


#### Make DB migrations, enter Django shell, other dev helper commands

<details><summary><i>Click to expand...</i></summary>

```bash
# generate the database migrations after changes to models.py
cd archivebox/
./manage.py makemigrations

# enter a python shell or a SQL shell
cd path/to/test/data/
archivebox shell
archivebox manage dbshell

# generate a graph of the ORM models
brew install graphviz
pip install pydot graphviz
archivebox manage graph_models -a -o orm.png
open orm.png

# list all models with field db info and methods
archivebox manage list_model_info --all --signature --db-type --field-class

# print all django settings
archivebox manage print_settings
archivebox manage print_settings --format=yaml    # pip install pyyaml

# autogenerate an admin.py from given app models
archivebox manage admin_generator core > core/admin.py

# dump db data to a script that re-populates it
archivebox manage dumpscript core > scripts/testdata.py
archivebox manage reset core
archivebox manage runscript testdata

# resetdb and clear all data!
archivebox manage reset_db

# use django-tui to interactively explore commands
pip install django-tui
# ensure django-tui is in INSTALLED_APPS: core/settings.py
archivebox manage tui

# show python and JS package dependency trees
pdm list --tree
npm ls --all
```

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/dc3e9f8c-9544-46e0-a7f0-30f571b72022" width="600px" alt="ArchiveBox ORM models relatinoship graph"/>

- https://django-extensions.readthedocs.io/en/latest/command_extensions.html
- https://stackoverflow.com/questions/1074212/how-can-i-see-the-raw-sql-queries-django-is-running
- https://github.com/anze3db/django-tui (explore `manage.py` commands as TUI)
- https://github.com/bloomberg/memray (advanced python profiler)
- https://github.com/laixintao/flameshow (display flamegraphs in terminal)
- https://github.com/taliraj/django-migrations-tui (explore migrations as TUI)

</details>

#### Contributing a new extractor

<details><summary><i>Click to expand...</i></summary>

<br/><br/>

ArchiveBox [`extractors`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/extractors/media.py) are external binaries or Python/Node scripts that ArchiveBox runs to archive content on a page.

Extractors take the URL of a page to archive, write their output to the filesystem `data/archive/TIMESTAMP/EXTRACTOR/...`, and return an [`ArchiveResult`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/core/models.py#:~:text=return%20qs-,class%20ArchiveResult,-(models.Model)%3A) entry which is saved to the database (visible on the `Log` page in the UI).

*Check out how we added **[`archivebox/extractors/singlefile.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/extractors/singlefile.py)** as an example of the process: [Issue #399](https://github.com/ArchiveBox/ArchiveBox/issues/399) + [PR #403](https://github.com/ArchiveBox/ArchiveBox/pull/403).*

<br/>


**The process to contribute a new extractor is like this:**

> [!IMPORTANT]
> This process is getting much easier after v0.8.x, there is a new plugin system under development: https://github.com/ArchiveBox/ArchiveBox/releases/tag/v0.8.4-rc

1. [Open an issue](https://github.com/ArchiveBox/ArchiveBox/issues/new?assignees=&labels=changes%3A+behavior%2Cstatus%3A+idea+phase&template=feature_request.md&title=Feature+Request%3A+...) with your propsoed implementation (please link to the pages of any new external dependencies you plan on using)
2. Ensure any dependencies needed are easily installable via a package managers like `apt`, `brew`, `pip3`, `npm`
   (Ideally, prefer to use external programs available via `pip3` or `npm`, however we do support using any binary installable via package manager that exposes a CLI/Python API and writes output to stdout or the filesystem.)
3. Create a new file in [`archivebox/extractors/EXTRACTOR.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/extractors) (copy an existing extractor like [`singlefile.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/extractors/singlefile.py) as a template)
4. Add config settings to enable/disable any new dependencies and the extractor as a whole, e.g. `USE_DEPENDENCYNAME`, `SAVE_EXTRACTORNAME`, `EXTRACTORNAME_SOMEOTHEROPTION` in [`archivebox/config.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/config.py)
5. Add a preview section to [`archivebox/templates/core/snapshot.html`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/templates/core/snapshot.html) to view the output, and a column to [`archivebox/templates/core/index_row.html`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/templates/core/index_row.html) with an icon for your extractor
6. Add an integration test for your extractor in [`tests/test_extractors.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/tests/test_extractors.py)
7. [Submit your PR for review!](https://github.com/ArchiveBox/ArchiveBox/blob/dev/.github/CONTRIBUTING.md) 🎉
8. Once merged, please document it in these places and anywhere else you see info about other extractors:
  - https://github.com/ArchiveBox/ArchiveBox#output-formats
  - https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#archive-method-toggles
  - https://github.com/ArchiveBox/ArchiveBox/wiki/Install#dependencies

<br/><br/>

</details>

#### Build the docs, pip package, and docker image

<details><summary><i>Click to expand...</i></summary>

(Normally CI takes care of this, but these scripts can be run to do it manually)
```bash
./bin/build.sh

# or individually:
./bin/build_docs.sh
./bin/build_pip.sh
./bin/build_docker.sh
```

</details>

#### Roll a release

<details><summary><i>Click to expand...</i></summary>

(Normally CI takes care of this, but these scripts can be run to do it manually)
```bash
./bin/release.sh

# or individually:
./bin/release_docs.sh
./bin/release_pip.sh
./bin/release_docker.sh
```

</details>

---

## Further Reading

<img src="https://raw.githubusercontent.com/Monadical-SAS/redux-time/HEAD/examples/static/jeremy.jpg" width="100px" align="right"/>

- [ArchiveBox.io Website](https://archivebox.io) / [ArchiveBox Github (Source Code)](https://github.com/ArchiveBox/ArchiveBox) / [ArchiveBox Demo Server](https://demo.archivebox.io)
- [Documentation (Github Wiki)](https://github.com/ArchiveBox/ArchiveBox/wiki) / [API Reference Docs (ReadTheDocs)](https://docs.archivebox.io) / [Roadmap](https://github.com/ArchiveBox/ArchiveBox/wiki/Roadmap) / [Changelog](https://github.com/ArchiveBox/ArchiveBox/releases)
- [Bug Tracker (Github Issues)](https://github.com/ArchiveBox/ArchiveBox/issues) / [Discussions (Github Discussions)](https://github.com/ArchiveBox/ArchiveBox/discussions) / [Community Chat Forum (Zulip)](https://zulip.archivebox.io)
- Find us on social media: [Twitter `@ArchiveBoxApp`](https://twitter.com/ArchiveBoxApp), [LinkedIn](https://www.linkedin.com/company/archivebox/), [YouTube](https://www.youtube.com/@ArchiveBoxApp), [SaaSHub](https://www.saashub.com/archivebox), [Alternative.to](https://alternativeto.net/software/archivebox/about/), [Reddit](https://www.reddit.com/r/ArchiveBox/)

---

<br/>
<div align="center" style="text-align: center">
<b><a href="https://docs.sweeting.me/s/archivebox-consulting-services">🏛️ Contact us for professional support 💬</a></b><br/>
<br/><br/>
<a href="https://hcb.hackclub.com/donations/start/archivebox"><img src="https://img.shields.io/badge/Donate-Directly-%13DE5D26.svg"/></a> &nbsp;
<a href="https://github.com/sponsors/pirate"><img src="https://img.shields.io/badge/Github_Sponsors-%23B7CDFE.svg"/></a> &nbsp;
<a href="https://www.patreon.com/theSquashSH"><img src="https://img.shields.io/badge/Patreon-%23DD5D76.svg"/></a> &nbsp;
<a href="https://paypal.me/NicholasSweeting"><img src="https://img.shields.io/badge/Paypal-%23FFD141.svg"/></a> &nbsp;
<a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Donations"><img src="https://img.shields.io/badge/BTC%5CETH-%231a1a1a.svg"/></a>
<br/>
<sup><i>ArchiveBox operates as a US 501(c)(3) nonprofit <a href="https://en.wikipedia.org/wiki/Fiscal_sponsorship">FSP</a> (sponsored by <a href="https://hackclub.com/hcb?ref=donation">HCB</a>), <a href="https://hcb.hackclub.com/donations/start/archivebox">direct donations</a> are tax-deductible.</i></sup>
<br/><br/>
<a href="https://twitter.com/ArchiveBoxApp"><img src="https://img.shields.io/badge/Tweet-%40ArchiveBoxApp-blue.svg?style=flat"/></a>&nbsp;
<a href="https://github.com/ArchiveBox/ArchiveBox"><img src="https://img.shields.io/github/stars/ArchiveBox/ArchiveBox.svg?style=flat&label=Star+on+Github"/></a>&nbsp;
<a href="https://zulip.archivebox.io/"><img src="https://img.shields.io/badge/Join_Our_Community-Zulip_Forum-%23B7EDFE.svg"/></a><br/><br/>
<hr/>
<i>✨ Have spare CPU/disk/bandwidth after all your 网站存档爬 and want to help the world?<br/>Check out our <a href="https://github.com/ArchiveBox/good-karma-kit">Good Karma Kit</a>...</i>
</div>
