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

if [[ -f "$REPO_DIR/.venv/bin/activate" ]]; then
    source "$REPO_DIR/.venv/bin/activate"
else
    echo "[!] Warning: No virtualenv presesnt in $REPO_DIR.venv"
fi
cd "$REPO_DIR"


echo "[*] Cleaning up build dirs"
cd "$REPO_DIR"
rm -Rf build dist

echo "[+] Building sdist, bdist_wheel, and egg_info"
python3 setup.py \
    sdist --dist-dir=./pip_dist \
    bdist_wheel --dist-dir=./pip_dist \
    egg_info --egg-base=./pip_dist
