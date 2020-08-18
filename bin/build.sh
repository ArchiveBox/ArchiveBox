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

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && cd .. && pwd )"

source "$REPO_DIR/.venv/bin/activate"
cd "$REPO_DIR"

# echo "[*] Fetching latest docs version"
# cd "$REPO_DIR/docs"
# git pull
# cd "$REPO_DIR"

# echo "[+] Building docs"
# sphinx-apidoc -o docs archivebox
# cd "$REPO_DIR/docs"
# make html
# cd "$REPO_DIR"

echo "[*] Cleaning up build dirs"
cd "$REPO_DIR"
rm -Rf build dist archivebox.egg-info

echo "[+] Building sdist, bdist_egg, and bdist_wheel"
python3 setup.py sdist bdist_egg bdist_wheel

echo "[+] Building docker image in the background..."
docker build . -t archivebox \
               -t archivebox:latest > /tmp/archivebox_docker_build.log 2>&1 &
ps "$!"

echo "[√] Done. Install the built package by running:"
echo "    python3 setup.py install"
echo "    # or"
echo "    pip3 install ."
