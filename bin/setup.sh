#!/usr/bin/env bash
# ArchiveBox Setup Script (Ubuntu/Debian/FreeBSD/macOS)
#   - Project Homepage: https://github.com/ArchiveBox/ArchiveBox
#   - Install Documentation: https://github.com/ArchiveBox/ArchiveBox/wiki/Install
# Script Usage:
#    curl -fsSL 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/dev/bin/setup.sh' | bash
#           (aka https://docker-compose.archivebox.io)

### Bash Environment Setup
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
# https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html
# set -o xtrace
# set -x
# shopt -s nullglob
set -o errexit
set -o errtrace
set -o nounset
set -o pipefail
# IFS=$'\n'

clear

if [ $(id -u) -eq 0 ]; then
    echo
    echo "[X] You cannot run this script as root. You must run it as a non-root user with sudo ability."
    echo "    Create a new non-privileged user 'archivebox' if necessary."
    echo "      adduser archivebox && usermod -a archivebox -G sudo && su archivebox"
    echo "    https://www.digitalocean.com/community/tutorials/how-to-create-a-new-sudo-enabled-user-on-ubuntu-20-04-quickstart"
    echo "    https://www.vultr.com/docs/create-a-sudo-user-on-freebsd"
    echo "    Then re-run this script as the non-root user."
    echo
    exit 2
fi

if (which docker > /dev/null && docker pull archivebox/archivebox:latest); then
    echo "[+] Initializing an ArchiveBox data folder at ~/archivebox/data using Docker Compose..."
    mkdir -p ~/archivebox/data || exit 1
    cd ~/archivebox
    if [ -f "./index.sqlite3" ]; then
        mv -i ~/archivebox/* ~/archivebox/data/
    fi
    curl -fsSL 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/stable/docker-compose.yml' > docker-compose.yml
    mkdir -p ./etc
    curl -fsSL 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/stable/etc/sonic.cfg' > ./etc/sonic.cfg
    docker compose run --rm archivebox init --setup
    echo
    echo "[+] Starting ArchiveBox server using: docker compose up -d..."
    docker compose up -d
    sleep 7
    which open > /dev/null && open "http://127.0.0.1:8000" || true
    echo
    echo "[√] Server started on http://0.0.0.0:8000 and data directory initialized in ~/archivebox/data. Usage:"
    echo "    cd ~/archivebox"
    echo "    docker compose ps"
    echo "    docker compose down"
    echo "    docker compose pull"
    echo "    docker compose up"
    echo "    docker compose run archivebox manage createsuperuser"
    echo "    docker compose run archivebox add 'https://example.com'"
    echo "    docker compose run archivebox list"
    echo "    docker compose run archivebox help"
    exit 0
elif (which docker > /dev/null && docker pull archivebox/archivebox:latest); then
    echo "[+] Initializing an ArchiveBox data folder at ~/archivebox/data using Docker..."
    mkdir -p ~/archivebox/data || exit 1
    cd ~/archivebox
    if [ -f "./index.sqlite3" ]; then
        mv -i ~/archivebox/* ~/archivebox/data/
    fi
    cd ./data
    docker run -v "$PWD":/data -it --rm archivebox/archivebox:latest init --setup
    echo
    echo "[+] Starting ArchiveBox server using: docker run -d archivebox/archivebox..."
    docker run -v "$PWD":/data -it -d -p 8000:8000 --name=archivebox archivebox/archivebox:latest
    sleep 7
    which open > /dev/null && open "http://127.0.0.1:8000" || true
    echo
    echo "[√] Server started on http://0.0.0.0:8000 and data directory initialized in ~/archivebox/data. Usage:"
    echo "    cd ~/archivebox/data"
    echo "    docker ps --filter name=archivebox"
    echo "    docker kill archivebox"
    echo "    docker pull archivebox/archivebox"
    echo "    docker run -v $PWD:/data -d -p 8000:8000 --name=archivebox archivebox/archivebox"
    echo "    docker run -v $PWD:/data -it archivebox/archivebox manage createsuperuser"
    echo "    docker run -v $PWD:/data -it archivebox/archivebox add 'https://example.com'"
    echo "    docker run -v $PWD:/data -it archivebox/archivebox list"
    echo "    docker run -v $PWD:/data -it archivebox/archivebox help"
    exit 0
fi

echo
echo "[!] It's highly recommended to use ArchiveBox with Docker, but Docker wasn't found."
echo
echo "    ⚠️ If you want to use Docker, press [Ctrl-C] to cancel now. ⚠️"
echo "        Get Docker: https://docs.docker.com/get-docker/"
echo "        After you've installed Docker, run this script again."
echo
echo "Otherwise, install will continue with apt/brew/pkg + pip in 12s... (press [Ctrl+C] to cancel)"
echo
sleep 12 || exit 1
echo "Proceeding with system package manager..."
echo

echo "[i] ArchiveBox Setup Script 📦"
echo
echo "    This is a helper script which installs the ArchiveBox dependencies on your system using brew/apt/pip3."
echo "    You may be prompted for a sudo password in order to install the following:"
echo
echo "        - archivebox"
echo "        - python3, pip, nodejs, npm            (languages used by ArchiveBox, and its extractor modules)"
echo "        - curl, wget, git, youtube-dl, yt-dlp  (used for extracting title, favicon, git, media, and more)"
echo "        - chromium                             (skips this if any Chrome/Chromium version is already installed)"
echo
echo "    If you'd rather install these manually as-needed, you can find detailed documentation here:"
echo "        https://github.com/ArchiveBox/ArchiveBox/wiki/Install"
echo
echo "Continuing in 12s... (press [Ctrl+C] to cancel)"
echo
sleep 12 || exit 1
echo "Proceeding to install dependencies..."
echo

# On Linux:
if which apt-get > /dev/null; then
    echo "[+] Adding ArchiveBox apt repo and signing key to sources..."
    if ! (sudo apt install -y software-properties-common && sudo add-apt-repository -u ppa:archivebox/archivebox); then
        echo "deb http://ppa.launchpad.net/archivebox/archivebox/ubuntu focal main" | sudo tee /etc/apt/sources.list.d/archivebox.list
        echo "deb-src http://ppa.launchpad.net/archivebox/archivebox/ubuntu focal main" | sudo tee -a /etc/apt/sources.list.d/archivebox.list
        sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys C258F79DCC02E369
        sudo apt-get update -qq
    fi
    echo
    echo "[+] Installing ArchiveBox system dependencies using apt..."
    sudo apt-get install -y git python3 python3-pip python3-distutils wget curl yt-dlp ffmpeg git nodejs npm ripgrep
    sudo apt-get install -y libgtk2.0-0 libgtk-3-0 libnotify-dev libgconf-2-4 libnss3 libxss1 libasound2 libxtst6 xauth xvfb libgbm-dev || sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser || true
    sudo apt-get install -y archivebox
    sudo apt-get --only-upgrade install -y archivebox
    echo
    echo "[+] Installing ArchiveBox python dependencies using pip3..."
    sudo python3 -m pip install --upgrade --ignore-installed archivebox yt-dlp playwright
# On Mac:
elif which brew > /dev/null; then
    echo "[+] Installing ArchiveBox system dependencies using brew..."
    brew tap archivebox/archivebox
    brew update
    brew install python3 node git wget curl yt-dlp ripgrep
    brew install --fetch-HEAD -f archivebox
    echo
    echo "[+] Installing ArchiveBox python dependencies using pip3..."
    python3 -m pip install --upgrade --ignore-installed archivebox yt-dlp playwright
elif which pkg > /dev/null; then
    echo "[+] Installing ArchiveBox system dependencies using pkg and pip (python3.9)..."
    sudo pkg install -y python3 py39-pip py39-sqlite3 npm wget curl youtube_dl ffmpeg git ripgrep
    sudo pkg install -y chromium
    echo
    echo "[+] Installing ArchiveBox python dependencies using pip..."
    # don't use sudo here so that pip installs in $HOME/.local instead of into /usr/local
    python3 -m pip install --upgrade --ignore-installed archivebox yt-dlp playwright
else
    echo "[!] Warning: Could not find aptitude/homebrew/pkg! May not be able to install all dependencies automatically."
    echo
    echo "    If you're on macOS, make sure you have homebrew installed:     https://brew.sh/"
    echo "    If you're on Linux, only Ubuntu/Debian/BSD systems are officially supported with this script."
    echo "    If you're on Windows, this script is not officially supported (Docker is recommeded instead)."
    echo
    echo "See the README.md for Manual Setup & Troubleshooting instructions if you you're unable to run ArchiveBox after this script completes."
fi

echo

if ! (python3 --version && python3 -m pip --version && python3 -m django --version); then
    echo "[X] Python 3 pip was not found on your system!"
    echo "    You must first install Python >= 3.7 (and pip3):"
    echo "      https://www.python.org/downloads/"
    echo "      https://wiki.python.org/moin/BeginnersGuide/Download"
    echo "    After installing, run this script again."
    exit 1
fi

if ! (python3 -m django --version && python3 -m pip show archivebox && which -a archivebox); then
    echo "[X] Django and ArchiveBox were not found after installing!"
    echo "    Check to see if a previous step failed."
    echo
    exit 1
fi

# echo
# echo "[+] Upgrading npm and pip..."
# sudo npm i -g npm || true
# sudo python3 -m pip install --upgrade pip setuptools || true

echo
echo "[+] Installing Chromium binary using playwright..."
python3 -m playwright install --with-deps chromium || true
echo

echo
echo "[+] Initializing ArchiveBox data folder at ~/archivebox/data..."
mkdir -p ~/archivebox/data || exit 1
cd ~/archivebox
if [ -f "./index.sqlite3" ]; then
    mv -i ~/archivebox/* ~/archivebox/data/
fi
cd ./data
: | python3 -m archivebox init --setup || true   # pipe in empty command to make sure stdin is closed
# init shows version output at the end too
echo
echo "[+] Starting ArchiveBox server using: nohup archivebox server &..."
nohup python3 -m archivebox server 0.0.0.0:8000 > ./logs/server.log 2>&1 &
sleep 7
which open > /dev/null && open "http://127.0.0.1:8000" || true
echo
echo "[√] Server started on http://0.0.0.0:8000 and data directory initialized in ~/archivebox/data. Usage:"
echo "    cd ~/archivebox/data                               # see your data dir"
echo "    archivebox server --quick-init 0.0.0.0:8000        # start server process"
echo "    archivebox manage createsuperuser                  # add an admin user+pass"
echo "    ps aux | grep archivebox                           # see server process pid"
echo "    pkill -f archivebox                                # stop the server"
echo "    pip install --upgrade archivebox; archivebox init  # update versions"
echo "    archivebox add 'https://example.com'"              # archive a new URL
echo "    archivebox list                                    # see URLs archived"
echo "    archivebox help                                    # see more help & examples"
