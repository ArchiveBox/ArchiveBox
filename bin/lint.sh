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

FAILED=0

echo "[*] Running ruff..."
if ruff check --fix archivebox; then
    echo "√ No errors found."
else
    FAILED=1
fi

echo

echo "[*] Running pyright..."
if pyright; then
    echo "√ No errors found."
else
    FAILED=1
fi

echo

echo "[*] Running ty..."
if ty check --force-exclude --exclude '**/migrations/**' archivebox; then
    echo "√ No errors found."
else
    FAILED=1
fi

exit "$FAILED"
