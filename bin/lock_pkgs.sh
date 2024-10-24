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

cd "$REPO_DIR"

py_version="$(grep -E '^version = ' pyproject.toml | awk '{print $3}' | jq -r)"
# js_version="$(jq -r '.version' ${REPO_DIR}/etc/package.json)"

# if [[ "$py_version" != "$js_version" ]]; then
#     echo "[❌] Version in pyproject.toml ($py_version) does not match version in etc/package.json ($js_version)!"
#     exit 1
# fi

echo "[🔒] Locking all ArchiveBox dependencies (pip, npm)"
echo
echo "pyproject.toml:              archivebox $py_version"
# echo "package.json:                archivebox $js_version"
echo
echo

echo "[*] Cleaning up old lockfiles and build files"
deactivate 2>/dev/null || true
rm -Rf build dist
rm -f uv.lock
rm -f requirements.txt
# rm -f package-lock.json
# rm -f archivebox/package.json
# rm -f archivebox/package-lock.json
# rm -Rf ./.venv
# rm -Rf ./node_modules
# rm -Rf ./archivebox/node_modules

echo
echo

echo "[+] Generating dev & prod requirements.txt & pdm.lock from pyproject.toml..."
uv venv --allow-existing --python 3.12
source .venv/bin/activate
echo
echo "pyproject.toml:    archivebox $(grep 'version = ' pyproject.toml | awk '{print $3}' | jq -r)"
echo "$(which python):   $(python --version | head -n 1)"
echo "$(which uv):       $(uv --version | head -n 1)"

echo
# https://pdm-project.org/latest/usage/lockfile/
# prod
uv lock
uv pip compile pyproject.toml --all-extras -o requirements.txt >/dev/null
uv sync --all-extras --frozen 2>/dev/null

# echo
# echo "[+] Generating package-lock.json from etc/package.json..."
# npm install -g npm
# npm config set fund false --location=global
# npm config set audit false --location=global
# cd etc
# echo
# echo "etc/package.json:  archivebox $(jq -r '.version' etc/package.json)"
# echo
# echo "$(which node):     $(node --version | head -n 1)"
# echo "$(which npm):      $(npm --version | head -n 1)"

# echo
# npm install --package-lock-only --prefer-offline

echo
echo "[√] Finished. Don't forget to commit the new lockfiles:"
echo
ls "pyproject.toml" | cat
ls "requirements.txt" | cat
ls "uv.lock" | cat
# echo
# ls "package.json" | cat
# ls "package-lock.json" | cat
# ls "archivebox/package.json" | cat
# ls "archivebox/package-lock.json" | cat
