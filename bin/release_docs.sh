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
VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
SHORT_VERSION="$(echo "$VERSION" | perl -pe 's/(\d+)\.(\d+)\.(\d+)/$1.$2/g')"
cd "$REPO_DIR"


echo "[^] Pushing docs to github"
cd docs/
git commit -am "$NEW_VERSION release"
git push
git tag -a "v$NEW_VERSION" -m "v$NEW_VERSION"
git push origin master
git push origin --tags
