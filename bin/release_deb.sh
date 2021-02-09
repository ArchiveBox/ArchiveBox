#!/usr/bin/env bash

### Bash Environment Setup
# http://redsymbol.net/articles/unofficial-bash-strict-mode/
# https://www.gnu.org/software/bash/manual/html_node/The-Set-Builtin.html
# set -o xtrace
set -o errexit
set -o errtrace
set -o nounset
set -o pipefail
IFS=$'\n'

PGP_KEY_ID="${PGP_KEY_ID:-7D5695D3B618872647861D51C38137A7C1675988}"


REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && cd .. && pwd )"
VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
cd "$REPO_DIR"

CURRENT_PLAFORM="$(uname)"
REQUIRED_PLATFORM="Linux"
if [[ "$CURRENT_PLAFORM" != "$REQUIRED_PLATFORM" ]]; then
   echo "[!] Skipping the Debian package build on $CURRENT_PLAFORM (it can only be run on $REQUIRED_PLATFORM)."
   exit 0
fi


[[ "$PGP_PUBLIC_KEY" ]] && echo "$PGP_PUBLIC_KEY" > /tmp/archivebox_gpg.key.pub
[[ "$PGP_PRIVATE_KEY" ]] && echo "$PGP_PRIVATE_KEY" > /tmp/archivebox_gpg.key

echo "[+] Loading PGP keys from env vars and filesystem..."
gpg --import /tmp/archivebox_gpg.key.pub || true
gpg --import --allow-secret-key-import /tmp/archivebox_gpg.key || true


echo "[*] Signing build and changelog with PGP..."
debsign -k "$PGP_KEY_ID" "deb_dist/archivebox_${VERSION}-${DEBIAN_VERSION}_source.changes"

# make sure you have this in ~/.dput.cf:
#     [archivebox-ppa]
#     fqdn: ppa.launchpad.net
#     method: ftp
#     incoming: ~archivebox/ubuntu/archivebox/
#     login: anonymous
#     allow_unsigned_uploads: 0


echo "[^] Uploading to launchpad.net"
dput archivebox "deb_dist/archivebox_${VERSION}-1_source.changes"
