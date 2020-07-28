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

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && cd .. && pwd )"
VERSION_FILE="$DIR/archivebox/VERSION"

function bump_semver {
    echo "$1" | awk -F. '{$NF = $NF + 1;} 1' | sed 's/ /./g'
}

source "$DIR/.venv/bin/activate"
cd "$DIR"

OLD_VERSION="$(cat "$VERSION_FILE")"
NEW_VERSION="$(bump_semver "$OLD_VERSION")"

if [ -z "$(git status --porcelain)" ]; then 
    echo "[*] Bumping VERSION from $OLD_VERSION to $NEW_VERSION"
    echo "$NEW_VERSION" > "$VERSION_FILE"
else
    echo "[X] Commit your changes and make sure the Git state is clean before proceeding."
    exit 4
fi

echo "[*] Fetching latest docs version"
cd "$DIR/docs"
git pull

echo "[*] Cleaning up build dirs"
cd "$DIR"
rm -Rf build dist

echo "[*] Building sdist and bdist_wheel"
python3 setup.py sdist bdist_wheel

echo "[^] Uploading to test.pypi.org"
python3 -m twine upload --repository testpypi dist/*

echo "[^] Uploading to pypi.org"
python3 -m twine upload --repository pypi dist/*

echo "[√] Done. Published version v$NEW_VERSION"
