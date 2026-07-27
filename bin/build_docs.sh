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
export ABXPKG_LIB_DIR="${ABXPKG_LIB_DIR:-$REPO_DIR/.venv/abxpkg}"
mkdir -p "$ABXPKG_LIB_DIR/env/bin"

resolve_docs_binary() {
    local binary_name="$1"
    uv run --no-cache --project "$REPO_DIR" --no-sync --no-sources abxpkg env \
        --install \
        --lib="$ABXPKG_LIB_DIR" \
        --binproviders=env,apt,brew \
        "$binary_name" >/dev/null
    test -L "$ABXPKG_LIB_DIR/env/bin/$binary_name"
    test -x "$ABXPKG_LIB_DIR/env/bin/$binary_name"
}

resolve_docs_binary make
MAKE_BINARY="$ABXPKG_LIB_DIR/env/bin/make"

if [[ -f "$REPO_DIR/.venv/bin/activate" ]]; then
    source "$REPO_DIR/.venv/bin/activate"
else
    echo "[!] Warning: No virtualenv present in $REPO_DIR/.venv"
fi
cd "$REPO_DIR"


echo "[+] Building docs"
cd "$REPO_DIR/docs"
"$MAKE_BINARY" clean
"$MAKE_BINARY" html
# open docs/_build/html/index.html to see the output
cd "$REPO_DIR"
