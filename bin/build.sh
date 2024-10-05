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

# pipenv install --dev

# the order matters
./bin/build_docs.sh
./bin/build_pip.sh
./bin/build_docker.sh

echo "[√] Done. Install the built package by running:"
echo "    python3 setup.py install"
echo "    # or"
echo "    pip3 install ."
