#!/bin/bash

echo "[i] Installing bookmark-archiver dependencies.  This script may ask for your password in order to install the following:"
echo "    - Chromium Browser   (see README for Chromium instructions)"
echo "    - python3"
echo "    - wget"
echo "    - curl"
echo ""
echo "    You may follow manual setup instructions in README.md instead if you prefer not to run an unknown script"
echo "    Press Ctrl+C in the next 5 seconds to cancel, or don't do anything to continue..."
sleep 5

echo ""

if which apt; then
    # On Linux:
    echo "[+] Adding Google Chrome apt signing key"
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
    echo "[+] Adding Google Chrome apt source repo"
    sudo sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list'
    echo "[+] Updating repo list"
    apt update
    echo "[+] Installing Google-Chrome-Beta, python3, wget"
    apt install google-chrome-beta python3 wget
elif which brew; then
    # On Mac:
    echo "[+] Installing Google-Chrome-Canary, python3, wget"
    brew install Caskroom/versions/google-chrome-canary wget python3  # or chromium, up to you
    echo "[+] Linking Google-Chrome-Canary to /usr/local/bin/google-chrome"
    echo -e '#!/bin/bash\n/Applications/Google\ Chrome\ Canary.app/Contents/MacOS/Google\ Chrome\ Canary "$@"' > /usr/local/bin/google-chrome
    chmod +x /usr/local/bin/google-chrome
else
    echo "[X] Could not find aptitude or homebrew!"
    echo "If you're on macOS, make sure you have homebrew installed:     https://brew.sh/"
    echo "If you're on Ubuntu/Debian, make sure you have apt installed:  https://help.ubuntu.com/lts/serverguide/apt.html"
    echo "(those are the only currently supported systems)"
    echo "See the README.md for manual setup instructions."
    exit 1
fi

# Check:
google-chrome --version && which wget && which python3 && which curl && echo "[√] All dependencies installed." && exit 0

echo "[X] Failed to install some dependencies"
echo "    Try the manual setup instructions in the README, or open an issue on github to get help: https://github.com/pirate/bookmark-archiver/issues"
exit 1
