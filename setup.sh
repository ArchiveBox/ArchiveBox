#!/bin/bash
# Bookmark Archiver Setup Script
# Nick Sweeting 2017 | MIT License
# https://github.com/pirate/bookmark-archiver

echo "[i] Installing bookmark-archiver dependencies. 📦"
echo ""
echo "    You may be prompted for a password in order to install the following dependencies:"
echo "        - Chromium Browser   (see README for Google-Chrome instructions instead)"
echo "        - python3"
echo "        - wget"
echo "        - curl"
echo ""
echo "    You may follow Manual Setup instructions in README.md instead if you prefer not to run an unknown script."
echo "    Press enter to continue, or Ctrl+C to cancel..."
read

echo ""

# On Linux:
if which apt-get > /dev/null; then
    echo "[+] Updating apt repos..."
    apt update -q
    if which google-chrome; then
        echo "[i] You already have google-chrome installed, if you would like to download chromium-browser instead (they work pretty much the same), follow the Manual Setup instructions"
        echo "[+] Linking $(which google-chrome) -> /usr/bin/chromium-browser (press enter to continue, or Ctrl+C to cancel...)"
        read
        sudo ln -s "$(which google-chrome)" /usr/bin/chromium-browser
    elif which chromium-browser; then
        echo "[i] chromium-browser already installed, using existing installation."
        apt upgrade chromium-browser -y
    else
        echo "[+] Installing chromium-browser..."
        apt install chromium-browser -y
    fi
    echo "[+] Installing python3, wget, curl..."
    apt install python3 python3-pip wget curl
    pip3 install requests

# On Mac:
elif which brew > /dev/null; then   # 🐍 eye of newt
    if ls /Applications/Google\ Chrome.app > /dev/null; then
        echo "[+] Linking /usr/local/bin/google-chrome -> /Applications/Google Chrome.app"
        echo -e '#!/bin/bash\n/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome "$@"' > /usr/local/bin/chromium-browser
        chmod +x /usr/local/bin/chromium-browser

    elif which chromium-browser; then
        brew cask upgrade chromium-browser
        echo "[+] Linking /usr/local/bin/chromium-browser -> /Applications/Chromium.app"
        echo -e '#!/bin/bash\n/Applications/Chromium.app/Contents/MacOS/Chromium "$@"' > /usr/local/bin/chromium-browser
        chmod +x /usr/local/bin/chromium-browser

    else
        echo "[+] Installing chromium-browser..."
        brew cask install chromium
        echo "[+] Linking /usr/local/bin/chromium-browser -> /Applications/Chromium.app"
        echo -e '#!/bin/bash\n/Applications/Chromium.app/Contents/MacOS/Chromium "$@"' > /usr/local/bin/chromium-browser
        chmod +x /usr/local/bin/chromium-browser
    fi
    echo "[+] Installing python3, wget, curl  (ignore 'already installed' warnings)..."
    brew install python3 wget curl
    pip3 install requests
else
    echo "[X] Could not find aptitude or homebrew! ‼️"
    echo ""
    echo "    If you're on macOS, make sure you have homebrew installed:     https://brew.sh/"
    echo "    If you're on Ubuntu/Debian, make sure you have apt installed:  https://help.ubuntu.com/lts/serverguide/apt.html"
    echo "    (those are the only currently supported systems)"
    echo ""
    echo "See the README.md for Manual Setup & Troubleshooting instructions."
    exit 1
fi

# Check:
echo ""
echo "[*] Checking installed versions:"
which chromium-browser &&
chromium-browser --version &&
which wget &&
which python3 &&
which curl &&
echo "[√] All dependencies installed. ✅" &&
exit 0

echo ""
echo "[X] Failed to install some dependencies! ‼️"
echo "    - Try the Manual Setup instructions in the README.md"
echo "    - Try the Troubleshooting: Dependencies instructions in the README.md"
echo "    - Open an issue on github to get help: https://github.com/pirate/bookmark-archiver/issues"
exit 1
