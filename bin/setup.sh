#!/usr/bin/env bash
# ArchiveBox Setup Script: https://github.com/ArchiveBox/ArchiveBox
# Usage:
#    curl 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/dev/bin/setup.sh' | sh

if (which docker-compose > /dev/null && docker pull archivebox/archivebox); then
    echo "[+] Initializing an ArchiveBox data folder at ~/archivebox/data using Docker Compose..."
    mkdir -p ~/archivebox
    cd ~/archivebox
    mkdir -p data
    if [[ -f "./index.sqlite3" ]]; then
        mv ~/archivebox/* ~/archivebox/data/
    fi
    curl -O 'https://raw.githubusercontent.com/ArchiveBox/ArchiveBox/master/docker-compose.yml'
    docker-compose run --rm archivebox init --setup
    docker-compose up -d
    sleep 7
    open http://127.0.0.1:8000 || true
    exit 0
elif (which docker > /dev/null && docker pull archivebox/archivebox); then
    echo "[+] Initializing an ArchiveBox data folder at ~/archivebox using Docker..."
    mkdir -p ~/archivebox
    cd ~/archivebox
    if [[ -f "./data/index.sqlite3" ]]; then
        cd ./data
    fi
    docker run -v "$PWD":/data -it --rm archivebox/archivebox init --setup
    docker run -v "$PWD":/data -it -d -p 8000:8000 archivebox/archivebox
    sleep 7
    open http://127.0.0.1:8000 || true
    exit 0
fi

echo "[!] It's highly recommended to use Docker instead of running this script. ⚠️"
echo "    Docker is safer and easier to set up, and includes everything working out-of-the-box:"
echo "        https://github.com/ArchiveBox/ArchiveBox/wiki/Docker"
echo ""
echo "Continuing in 5s... (press [Ctrl+C] to cancel)"
sleep 5 || exit 1

echo "[i] ArchiveBox Setup Script 📦"
echo ""
echo "    This is a helper script which installs the ArchiveBox dependencies on your system using brew/apt/pip3."
echo "    You may be prompted for a password in order to install the following:"
echo ""
echo "        - python3, python3-pip, python3-distutils"
echo "        - nodejs, npm                  (used for singlefile, readability, mercury, and more)"
echo "        - curl, wget, git, youtube-dl  (used for extracting title, favicon, git, media, and more)"
echo "        - chromium                     (skips this if any Chrome/Chromium version is already installed)"
echo ""
echo ""
echo "    If you'd rather install these manually as-needed, you can find detailed documentation here:"
echo "        https://github.com/ArchiveBox/ArchiveBox/wiki/Install"
echo ""
echo "Continuing in 10s... (press [Ctrl+C] to cancel)"
sleep 10 || exit 1
echo ""

# On Linux:
if which apt-get > /dev/null; then
    echo "[+] Adding ArchiveBox apt repo to sources..."
    if ! (sudo apt install -y software-properties-common && sudo add-apt-repository -u ppa:archivebox/archivebox); then
        echo "deb http://ppa.launchpad.net/archivebox/archivebox/ubuntu focal main" | sudo tee /etc/apt/sources.list.d/archivebox.list
        echo "deb-src http://ppa.launchpad.net/archivebox/archivebox/ubuntu focal main" | sudo tee -a /etc/apt/sources.list.d/archivebox.list
        sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys C258F79DCC02E369
        sudo apt-get update -qq
    fi
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
    echo "[!] Warning: Could not find aptitude or homebrew! May not be able to install all dependencies correctly."
    echo ""
    echo "    If you're on macOS, make sure you have homebrew installed:     https://brew.sh/"
    echo "    If you're on Ubuntu/Debian, make sure you have apt installed:  https://help.ubuntu.com/lts/serverguide/apt.html"
    echo "    (those are the only currently supported systems for the automatic setup script)"
    echo ""
    echo "See the README.md for Manual Setup & Troubleshooting instructions if you you're unable to run ArchiveBox after this script completes."
fi

# echo "[+] Upgrading npm and pip..."
# npm i -g npm
# pip3 install --upgrade pip setuptools

echo "[+] Installing ArchiveBox and its dependencies using pip..."
pip3 install --upgrade archivebox

echo "[+] Initializing ArchiveBox data folder at ~/archivebox..."
mkdir -p ~/archivebox
cd ~/archivebox
if [[ -f "./data/index.sqlite3" ]]; then
    cd ./data
fi
exec archivebox init --setup
