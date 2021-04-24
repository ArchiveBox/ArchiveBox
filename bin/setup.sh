#!/usr/bin/env sh
# ArchiveBox Setup Script: https://github.com/ArchiveBox/ArchiveBox
# Usage:
#    curl 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/dev/bin/setup.sh' | sh

clear

if (which docker-compose > /dev/null && docker pull archivebox/archivebox:latest); then
    echo "[+] Initializing an ArchiveBox data folder at ~/archivebox/data using Docker Compose..."
    mkdir -p ~/archivebox
    cd ~/archivebox
    mkdir -p data
    if [ -f "./index.sqlite3" ]; then
        mv ~/archivebox/* ~/archivebox/data/
    fi
    curl -O 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/master/docker-compose.yml'
    docker-compose run --rm archivebox init --setup
    echo
    echo "[+] Starting ArchiveBox server using: docker-compose up -d..."
    docker-compose up -d
    sleep 7
    open http://127.0.0.1:8000 || true
    echo
    echo "[√] Server started on http://0.0.0.0:8000 and data directory initialized in ~/archivebox/data. Usage:"
    echo "    cd ~/archivebox"
    echo "    docker-compose ps"
    echo "    docker-compose down"
    echo "    docker-compose pull"
    echo "    docker-compose up"
    echo "    docker-compose run archivebox manage createsuperuser"
    echo "    docker-compose run archivebox add 'https://example.com'"
    echo "    docker-compose run archivebox list"
    echo "    docker-compose run archivebox help"
    exit 0
elif (which docker > /dev/null && docker pull archivebox/archivebox:latest); then
    echo "[+] Initializing an ArchiveBox data folder at ~/archivebox using Docker..."
    mkdir -p ~/archivebox
    cd ~/archivebox
    if [ -f "./data/index.sqlite3" ]; then
        cd ./data
    fi
    docker run -v "$PWD":/data -it --rm archivebox/archivebox:latest init --setup
    echo
    echo "[+] Starting ArchiveBox server using: docker run -d archivebox/archivebox..."
    docker run -v "$PWD":/data -it -d -p 8000:8000 --name=archivebox archivebox/archivebox:latest
    sleep 7
    open http://127.0.0.1:8000 || true
    echo
    echo "[√] Server started on http://0.0.0.0:8000 and data directory initialized in ~/archivebox. Usage:"
    echo "    cd ~/archivebox"
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

echo ""
echo "[!] It's highly recommended to use ArchiveBox with Docker, but Docker wasn't found."
echo ""
echo "    ⚠️ If you want to use Docker, press [Ctrl-C] to cancel now. ⚠️"
echo "        Get Docker: https://docs.docker.com/get-docker/"
echo "        (after you've installed Docker, run this script again)"
echo ""
echo "Otherwise, install will continue with apt/brew/pip in 15s... (press [Ctrl+C] to cancel)"
echo ""
sleep 15 || exit 1


echo "[i] ArchiveBox Setup Script 📦"
echo ""
echo "    This is a helper script which installs the ArchiveBox dependencies on your system using brew/apt/pip3."
echo "    You may be prompted for a sudo password in order to install the following:"
echo ""
echo "        - archivebox"
echo "        - python3, pip, nodejs, npm    (languages used by ArchiveBox, and its extractor modules)"
echo "        - curl, wget, git, youtube-dl  (used for extracting title, favicon, git, media, and more)"
echo "        - chromium                     (skips this if any Chrome/Chromium version is already installed)"
echo ""
echo ""
echo "    If you'd rather install these manually as-needed, you can find detailed documentation here:"
echo "        https://github.com/ArchiveBox/ArchiveBox/wiki/Install"
echo ""
echo "Continuing in 15s... (press [Ctrl+C] to cancel)"
echo ""
sleep 15 || exit 1
echo ""

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
    echo "[+] Installing ArchiveBox and its dependencies using apt..."
    # sudo apt install -y git python3 python3-pip python3-distutils wget curl youtube-dl ffmpeg git nodejs npm ripgrep
    sudo apt-get install -y archivebox
    sudo apt-get --only-upgrade install -y archivebox

# On Mac:
elif which brew > /dev/null; then
    echo "[+] Installing ArchiveBox and its dependencies using brew..."
    brew tap archivebox/archivebox
    brew update
    brew install --fetch-HEAD -f archivebox
else
    echo "[!] Warning: Could not find aptitude or homebrew! May not be able to install all dependencies automatically."
    echo ""
    echo "    If you're on macOS, make sure you have homebrew installed:     https://brew.sh/"
    echo "    If you're on Linux, only Ubuntu/Debian systems are officially supported with this script."
    echo "    If you're on Windows, this script is not officially supported (Docker is recommeded instead)."
    echo ""
    echo "See the README.md for Manual Setup & Troubleshooting instructions if you you're unable to run ArchiveBox after this script completes."
fi

echo ""

if ! (python3 --version && python3 -m pip --version); then
    echo "[X] Python 3 pip was not found on your system, you must first install Python >= 3.7."
    echo "    https://www.python.org/downloads/"
    echo "    https://wiki.python.org/moin/BeginnersGuide/Download"
    echo "    (after installing, run this script again)"
    exit 1
fi

# echo "[+] Upgrading npm and pip..."
# npm i -g npm
# python3 -m pip install --upgrade pip setuptools

echo ""
echo "[+] Installing ArchiveBox and its dependencies using pip..."
python3 -m pip install --upgrade archivebox

echo
echo "[+] Initializing ArchiveBox data folder at ~/archivebox..."
mkdir -p ~/archivebox
cd ~/archivebox
if [ -f "./data/index.sqlite3" ]; then
    cd ./data
fi
: | archivebox init --setup || true   # pipe in empty command to make sure stdin is closed

echo
echo "[+] Starting ArchiveBox server using: nohup archivebox server &..."
nohup archivebox server 0.0.0.0:8000 > ./logs/server.log 2>&1 &
sleep 7
open http://127.0.0.1:8000 || true

echo
echo "[√] Server started on http://0.0.0.0:8000 and data directory initialized in ~/archivebox. Usage:"
echo "    cd ~/archivebox"
echo "    ps aux | grep archivebox"
echo "    pkill -f archivebox"
echo "    pip3 install --upgrade archviebox"
echo "    archivebox server --quick-init 0.0.0.0:8000"
echo "    archivebox manage createsuperuser"
echo "    archivebox add 'https://example.com'"
echo "    archivebox list"
echo "    archivebox help"
