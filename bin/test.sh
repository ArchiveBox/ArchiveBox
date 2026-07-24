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

mkdir -p "$DIR/tests/out"
if [ "$#" -eq 0 ]; then
    set -- archivebox/tests
fi
exec uv run --project "$DIR" --no-sync --no-sources pytest -s --basetemp="$DIR/tests/out" "$@"
