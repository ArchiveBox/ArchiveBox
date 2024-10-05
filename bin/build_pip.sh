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

# Generate pdm.lock, requirements.txt, and package-lock.json
bash ./bin/lock_pkgs.sh
source .venv/bin/activate

echo "[+] Building sdist, bdist_wheel, and egg_info"
rm -Rf build dist
uv build

echo
echo "[√] Finished. Built package in dist/"
