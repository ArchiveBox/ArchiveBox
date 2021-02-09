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


if [[ -f "$REPO_DIR/.venv/bin/activate" ]]; then
    source "$REPO_DIR/.venv/bin/activate"
else
    echo "[!] Warning: No virtualenv presesnt in $REPO_DIR.venv"
fi

# cleanup build artifacts
rm -Rf build deb_dist dist archivebox-*.tar.gz


# build source and binary packages
# make sure the stdeb.cfg file is up-to-date with all the dependencies
python3 setup.py --command-packages=stdeb.command \
    sdist_dsc --debian-version=$DEBIAN_VERSION \
    bdist_deb

# should output deb_dist/archivebox_0.5.4-1.{deb,changes,buildinfo,tar.gz}
