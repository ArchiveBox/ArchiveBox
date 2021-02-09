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


CURRENT_PLAFORM="$(uname)"
REQUIRED_PLATFORM="Linux"
if [[ "$CURRENT_PLAFORM" != "$REQUIRED_PLATFORM" ]]; then
   echo "[!] Skipping the Debian package build on $CURRENT_PLAFORM (it can only be run on $REQUIRED_PLATFORM)."
   exit 0
fi


REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && cd .. && pwd )"
VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
DEBIAN_VERSION="${DEBIAN_VERSION:-1}"
cd "$REPO_DIR"


echo "[+] Loading PGP keys from env vars and filesystem..."
# https://github.com/ArchiveBox/debian-archivebox/settings/secrets/actions
PGP_KEY_ID="${PGP_KEY_ID:-BC2D21B0D84E16C437300B8652423FBED1586F45}"
[[ "${PGP_PUBLIC_KEY:-}" ]] && echo "$PGP_PUBLIC_KEY" > /tmp/archivebox_gpg.key.pub
[[ "${PGP_PRIVATE_KEY:-}" ]] && echo "$PGP_PRIVATE_KEY" > /tmp/archivebox_gpg.key
gpg --import /tmp/archivebox_gpg.key.pub || true
gpg --import --allow-secret-key-import /tmp/archivebox_gpg.key || true
echo "$PGP_KEY_ID:6:" | gpg --import-ownertrust || true

echo "[*] Signing build and changelog with PGP..."
debsign  --re-sign -k "$PGP_KEY_ID" "deb_dist/archivebox_${VERSION}-${DEBIAN_VERSION}_source.changes"

# make sure you have this in ~/.dput.cf:
#     [archivebox-ppa]
#     fqdn: ppa.launchpad.net
#     method: ftp
#     incoming: ~archivebox/ubuntu/archivebox/
#     login: anonymous
#     allow_unsigned_uploads: 0


echo "[^] Uploading to launchpad.net"
dput -f archivebox "deb_dist/archivebox_${VERSION}-${DEBIAN_VERSION}_source.changes"
