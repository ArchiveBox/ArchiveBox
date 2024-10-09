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


# Run the linters and tests
# ./bin/lint.sh
# ./bin/test.sh

# # Run all the build scripts
# ./bin/build_git.sh
# ./bin/build_docs.sh
# ./bin/build_pip.sh
# ./bin/build_docker.sh

# Push relase to public repositories
# ./bin/release_docs.sh
./bin/release_git.sh "$@"
./bin/release_pip.sh "$@"
./bin/release_docker.sh "$@"

VERSION="$(grep '^version = ' "${REPO_DIR}/pyproject.toml" | awk -F'"' '{print $2}')"
echo "[√] Done. Published version v$VERSION"
