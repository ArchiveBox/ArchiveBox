#!/usr/bin/env bash
# ArchiveBox Setup Script
# https://github.com/ArchiveBox/ArchiveBox

echo "[i] ArchiveBox Setup Script 📦"
echo ""
echo "    This is a helper script which installs the ArchiveBox dependencies on your system using homebrew/aptitude."
echo "    You may be prompted for a password in order to install the following:"
echo ""
echo "        - python3, python3-pip, python3-distutils"
echo "        - curl"
echo "        - wget"
echo "        - git"
echo "        - youtube-dl"
echo "        - chromium-browser  (skip this if Chrome/Chromium is already installed)"
echo "        - nodejs            (used for singlefile, readability, mercury, and more)"
echo ""
echo "    If you'd rather install these manually, you can find documentation here:"
echo "        https://github.com/ArchiveBox/ArchiveBox/wiki/Install"
echo ""
read -p "Press [enter] to continue with the automatic install, or Ctrl+C to cancel..." REPLY
echo ""

# On Linux:
if which apt-get > /dev/null; then
    echo "[+] Adding ArchiveBox apt repo to sources..."
    sudo apt install software-properties-common
    sudo add-apt-repository -u ppa:archivebox/archivebox
    echo "[+] Installing python3, wget, curl..."
    sudo apt install -y git python3 python3-pip python3-distutils wget curl youtube-dl nodejs npm ripgrep
    # sudo apt install archivebox

    if which google-chrome; then
        echo "[i] You already have google-chrome installed, if you would like to download chromium instead (they work pretty much the same), follow the Manual Setup instructions"
        google-chrome --version
    elif which chromium-browser; then
        echo "[i] chromium-browser already installed, using existing installation."
        chromium-browser --version
    elif which chromium; then
        echo "[i] chromium already installed, using existing installation."
        chromium --version
    else
        echo "[+] Installing chromium..."
        sudo apt install chromium || sudo apt install chromium-browser
    fi

# On Mac:
elif which brew > /dev/null; then   # 🐍 eye of newt
    echo "[+] Installing python3, wget, curl  (ignore 'already installed' warnings)..."
    brew install git wget curl youtube-dl ripgrep node
    if which python3; then
        if python3 -c 'import sys; raise SystemExit(sys.version_info < (3,5,0))'; then
            echo "[√] Using existing $(which python3)..."
        else
            echo "[+] Installing python3..."
            brew install python3
        fi
    else
        echo "[+] Installing python3..."
        brew install python3
    fi

    if ls /Applications/Google\ Chrome*.app > /dev/null; then
        echo "[√] Using existing /Applications/Google Chrome.app"
    elif ls /Applications/Chromium.app; then
        echo "[√] Using existing /Applications/Chromium.app"
    elif which chromium-browser; then
        echo "[√] Using existing $(which chromium-browser)"
    elif which chromium; then
        echo "[√] Using existing $(which chromium)"
    else
        echo "[+] Installing chromium..."
        brew cask install chromium
    fi
else
    echo "[X] Could not find aptitude or homebrew! ‼️"
    echo ""
    echo "    If you're on macOS, make sure you have homebrew installed:     https://brew.sh/"
    echo "    If you're on Ubuntu/Debian, make sure you have apt installed:  https://help.ubuntu.com/lts/serverguide/apt.html"
    echo "    (those are the only currently supported systems for the automatic setup script)"
    echo ""
    echo "See the README.md for Manual Setup & Troubleshooting instructions."
    exit 1
fi

npm i -g npm
pip3 install --upgrade pip setuptools

pip3 install --upgrade archivebox
npm install -g 'git+https://github.com/ArchiveBox/ArchiveBox.git' 

# Check:
echo ""
echo "[*] Checking installed versions:"
echo "---------------------------------------------------"
which python3 &&
python3 --version | head -n 1 &&
echo "" &&
which git &&
git --version | head -n 1 &&
echo "" &&
which wget &&
wget --version | head -n 1 &&
echo "" &&
which curl &&
curl --version | head -n 1 &&
echo "" &&
which youtube-dl &&
youtube-dl --version | head -n 1 &&
echo "---------------------------------------------------" &&
archivebox version &&
echo "[√] All dependencies installed. ✅" &&
exit 0

echo "---------------------------------------------------"
echo "[X] Failed to install some dependencies! ‼️"
echo "    - Try the Manual Setup instructions in the README.md"
echo "    - Try the Troubleshooting: Dependencies instructions in the README.md"
echo "    - Open an issue on github to get help: https://github.com/ArchiveBox/ArchiveBox/issues"
exit 1
