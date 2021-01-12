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
source "./.venv/bin/activate"


# Make sure git is clean
if [ -z "$(git status --porcelain)" ] && [[ "$(git branch --show-current)" == "master" ]]; then 
    git pull
else
    echo "[!] Warning: git status is dirty!"
    echo "    Press Ctrl-C to cancel, or wait 10sec to continue..."
    sleep 10
fi

# Bump version number in source
function bump_semver {
    echo "$1" | awk -F. '{$NF = $NF + 1;} 1' | sed 's/ /./g'
}

OLD_VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
NEW_VERSION="$(bump_semver "$OLD_VERSION")"
echo "[*] Bumping VERSION from $OLD_VERSION to $NEW_VERSION"
contents="$(jq ".version = \"$NEW_VERSION\"" "$REPO_DIR/package.json")" && \
echo "${contents}" > package.json

