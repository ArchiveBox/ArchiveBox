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

echo "[*] Running ruff..."
ruff check archivebox
echo "√ No errors found."

echo

echo "[*] Running pyright..."
pyright
echo "√ No errors found."

echo

echo "[*] Running ty..."
ty check archivebox
echo "√ No errors found."
