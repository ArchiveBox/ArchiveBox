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


# Build docs, python package, and docker image
./bin/build_docs.sh
./bin/build_pip.sh
./bin/build_deb.sh
./bin/build_docker.sh


# Push build to github
echo "[^] Pushing source to github"
git add "$REPO_DIR/docs"
git add "$REPO_DIR/package.json"
git add "$REPO_DIR/package-lock.json"
git add "$REPO_DIR/archivebox.egg-info"
git commit -m "$NEW_VERSION release"
git tag -a "v$NEW_VERSION" -m "v$NEW_VERSION"
git push origin master
git push origin --tags


# Push releases to github
echo "[^] Uploading to test.pypi.org"
python3 -m twine upload --repository testpypi dist/*

echo "[^] Uploading to pypi.org"
python3 -m twine upload --repository pypi dist/*

echo "[^] Uploading to launchpad.net"
dput archivebox "deb_dist/archivebox_${NEW_VERSION}-1_source.changes"

echo "[^] Uploading docker image"
# docker login --username=nikisweeting
# docker login docker.pkg.github.com --username=pirate
docker push docker.io/nikisweeting/archivebox
docker push docker.io/archivebox/archivebox
docker push docker.pkg.github.com/archivebox/archivebox/archivebox

echo "[√] Done. Published version v$NEW_VERSION"
