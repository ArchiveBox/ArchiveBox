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
    echo "[!] Warning: No virtualenv presesnt in $REPO_DIR/.venv, creating one now..."
    python3 -m venv --system-site-packages --symlinks $REPO_DIR/.venv
fi
cd "$REPO_DIR"

# Generate pdm.lock, requirements.txt, and package-lock.json
bash ./bin/lock_pkgs.sh

echo "[+] Building sdist, bdist_wheel, and egg_info"
rm -Rf build dist
pdm build
cp dist/* ./pip_dist/

echo
echo "[√] Finished. Don't forget to commit the new sdist and wheel files in ./pip_dist/"
