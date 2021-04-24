#!/usr/bin/env bash
# ArchiveBox Setup Script
# https://github.com/ArchiveBox/ArchiveBox

echo "[!] It's highly recommended to use Docker instead of running this script. ⚠️"
echo "    Docker is safer and easier to set up, and includes everything working out-of-the-box:"
echo "        https://github.com/ArchiveBox/ArchiveBox/wiki/Docker"
echo ""
echo "Continuing in 5s... (press [Ctrl+C] to cancel)"
sleep 5
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
read -p "Press [enter] to continue with the automatic install, or Ctrl+C to cancel..." REPLY
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
archivebox init --setup && exit 0

echo "---------------------------------------------------"
echo "[X] Failed to install some dependencies! ‼️"
echo "    - Try the Manual Setup instructions in the README.md"
echo "    - Try the Troubleshooting: Dependencies instructions in the README.md"
echo "    - Open an issue on github to get help: https://github.com/ArchiveBox/ArchiveBox/issues"
exit 1
