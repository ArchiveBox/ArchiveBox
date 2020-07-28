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

source "$DIR/.venv/bin/activate"
cd "$DIR"

echo "[*] Fetching latest docs version"
cd "$DIR/docs"
git pull

echo "[*] Cleaning up build dirs"
cd "$DIR"
rm -Rf build dist

echo "[*] Bumping VERSION number"
nano "$DIR/archivebox/VERSION"

echo "[*] Building sdist and bdist_wheel"
python3 setup.py sdist bdist_wheel

echo "[*] Building sdist and bdist_wheel"
python3 setup.py sdist bdist_wheel

echo "[^] Uploading to test.pypi.org"
python3 -m twine upload --repository testpypi dist/*

echo "[^] Uploading to pypi.org"
python3 -m twine upload --repository pypi dist/*

echo "[√] Done. Now at version $(cat "$DIR/archivebox/VERSION")"
