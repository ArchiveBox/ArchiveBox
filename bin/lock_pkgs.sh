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

py_version="$(grep 'version = ' pyproject.toml | awk '{print $3}' | jq -r)"
js_version="$(jq -r '.version' package.json)"

if [[ "$py_version" != "$js_version" ]]; then
    echo "[❌] Version in pyproject.toml ($py_version) does not match version in package.json ($js_version)!"
    exit 1
fi

echo "[🔒] Locking all ArchiveBox dependencies (pip, npm)"
echo
echo "pyproject.toml:              archivebox $py_version"
echo "package.json:                archivebox $js_version"
echo
echo

echo "[*] Cleaning up old lockfiles and build files"
deactivate 2>/dev/null || true
rm -Rf build dist
rm -f pdm.lock
rm -f pdm.dev.lock
rm -f requirements.txt
rm -f requirements-dev.txt
rm -f package-lock.json
rm -f archivebox/package.json
rm -f archivebox/package-lock.json
rm -Rf ./.venv
rm -Rf ./node_modules
rm -Rf ./archivebox/node_modules

echo
echo

echo "[+] Generating dev & prod requirements.txt & pdm.lock from pyproject.toml..."
pip install --upgrade pip setuptools
pdm self update >/dev/null 2>&1 || true
pdm venv create 3.10
echo
echo "pyproject.toml:    archivebox $(grep 'version = ' pyproject.toml | awk '{print $3}' | jq -r)"
echo "$(which python):   $(python --version | head -n 1)"
echo "$(which pdm):      $(pdm --version | head -n 1)"
pdm info --env
pdm info

echo
# https://pdm-project.org/latest/usage/lockfile/
# prod
pdm lock --group=':all' --production --lockfile pdm.lock --strategy="cross_platform"
pdm sync --group=':all' --production --lockfile pdm.lock --clean
pdm export --group=':all' --production --lockfile pdm.lock --without-hashes -o requirements.txt
# cp ./pdm.lock ./pip_dist/
# cp ./requirements.txt ./pip_dist/

# dev
pdm lock --group=':all' --dev --lockfile pdm.dev.lock --strategy="cross_platform" 
pdm sync --group=':all' --dev --lockfile pdm.dev.lock --clean
pdm export --group=':all' --dev --lockfile pdm.dev.lock --without-hashes -o requirements-dev.txt
# cp ./pdm.dev.lock ./pip_dist/
# cp ./requirements-dev.txt ./pip_dist/

echo
echo "[+] Generating package-lock.json from package.json..."
npm install -g npm
echo
echo "package.json:    archivebox $(jq -r '.version' package.json)"
echo
echo "$(which node):   $(node --version | head -n 1)"
echo "$(which npm):    $(npm --version | head -n 1)"

echo
npm install --package-lock-only
cp package.json archivebox/package.json
cp package-lock.json archivebox/package-lock.json

echo
echo "[√] Finished. Don't forget to commit the new lockfiles:"
echo
ls "pyproject.toml" | cat
ls "pdm.lock" | cat
ls "pdm.dev.lock" | cat
ls "requirements.txt" | cat
ls "requirements-dev.txt" | cat
echo
ls "package.json" | cat
ls "package-lock.json" | cat
ls "archivebox/package.json" | cat
ls "archivebox/package-lock.json" | cat
