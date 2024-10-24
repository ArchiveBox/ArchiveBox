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
VERSION="$(grep '^version = ' "${REPO_DIR}/pyproject.toml" | awk -F'"' '{print $2}')"
cd "$REPO_DIR"


# Push build to github
echo "[^] Pushing release commit + tag to Github"
git tag -f -a "v$VERSION" -m "v$VERSION"
git push origin -f --tags
echo "    To finish publishing the release go here:"
echo "        https://github.com/ArchiveBox/ArchiveBox/releases/new"
