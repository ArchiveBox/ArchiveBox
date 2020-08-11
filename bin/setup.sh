#!/bin/bash
# ArchiveBox Setup Script
# Nick Sweeting 2017 | MIT License
# https://github.com/pirate/ArchiveBox

echo "[i] ArchiveBox Setup Script 📦"
echo ""
echo "    This is a helper script which installs the ArchiveBox dependencies on your system using homebrew/aptitude."
echo "    You may be prompted for a password in order to install the following:"
echo ""
echo "        - git"
echo "        - python3, python3-pip, python3-distutils"
echo "        - curl"
echo "        - wget"
echo "        - youtube-dl"
echo "        - chromium-browser  (skip this if Chrome/Chromium is already installed)"
echo ""
echo "    If you'd rather install these manually, you can find documentation here:"
echo "        https://github.com/pirate/ArchiveBox/wiki/Install"
echo ""
echo "Press enter to continue with the automatic install, or Ctrl+C to cancel..."
read

echo ""

# On Linux:
if which apt-get > /dev/null; then
    echo "[+] Updating apt repos..."
    apt update -q
    echo "[+] Installing python3, wget, curl..."
    apt install git python3 python3-pip python3-distutils wget curl youtube-dl

    if which google-chrome; then
        echo "[i] You already have google-chrome installed, if you would like to download chromium-browser instead (they work pretty much the same), follow the Manual Setup instructions"
        google-chrome --version
    elif which chromium-browser; then
        echo "[i] chromium-browser already installed, using existing installation."
        chromium-browser --version
    else
        echo "[+] Installing chromium-browser..."
        apt install chromium-browser
    fi

# On Mac:
elif which brew > /dev/null; then   # 🐍 eye of newt
    echo "[+] Installing python3, wget, curl  (ignore 'already installed' warnings)..."
    brew install git wget curl youtube-dl
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
    else
        echo "[+] Installing chromium-browser..."
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
echo "[√] All dependencies installed. ✅" &&
exit 0

echo "---------------------------------------------------"
echo "[X] Failed to install some dependencies! ‼️"
echo "    - Try the Manual Setup instructions in the README.md"
echo "    - Try the Troubleshooting: Dependencies instructions in the README.md"
echo "    - Open an issue on github to get help: https://github.com/pirate/ArchiveBox/issues"
exit 1
