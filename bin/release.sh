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

function bump_semver {
    echo "$1" | awk -F. '{$NF = $NF + 1;} 1' | sed 's/ /./g'
}

source "$REPO_DIR/.venv/bin/activate"
cd "$REPO_DIR"

OLD_VERSION="$(jq -r '.version' < "$REPO_DIR/package.json")"
NEW_VERSION="$(bump_semver "$OLD_VERSION")"

echo "[*] Fetching latest docs version"
cd "$REPO_DIR/docs"
git pull
cd "$REPO_DIR"

echo "[+] Building docs"
sphinx-apidoc -o docs archivebox
cd "$REPO_DIR/docs"
make html
cd "$REPO_DIR"

if [ -z "$(git status --porcelain)" ] && [[ "$(git branch --show-current)" == "master" ]]; then 
    git pull
else
    echo "[!] Warning: git status is dirty!"
    echo "    Press Ctrl-C to cancel, or wait 10sec to continue..."
    sleep 10
fi

echo "[*] Bumping VERSION from $OLD_VERSION to $NEW_VERSION"
contents="$(jq ".version = \"$NEW_VERSION\"" "$REPO_DIR/package.json")" && \
echo "${contents}" > package.json
git add "$REPO_DIR/docs"
git add "$REPO_DIR/package.json"
git add "$REPO_DIR/package-lock.json"

echo "[*] Cleaning up build dirs"
cd "$REPO_DIR"
rm -Rf build dist archivebox.egg-info

echo "[+] Building sdist and bdist_wheel"
python3 setup.py sdist bdist_egg bdist_wheel

echo "[^] Pushing source to github"
git add "$REPO_DIR/archivebox.egg-info"
git commit -m "$NEW_VERSION release"
git tag -a "v$NEW_VERSION" -m "v$NEW_VERSION"
git push origin master
git push origin --tags

echo "[^] Uploading to test.pypi.org"
python3 -m twine upload --repository testpypi dist/*

echo "[^] Uploading to pypi.org"
python3 -m twine upload --repository pypi dist/*

echo "[+] Building docker image"
docker build . -t archivebox \
               -t archivebox:latest \
               -t archivebox:$NEW_VERSION \
               -t docker.io/nikisweeting/archivebox:latest \
               -t docker.io/nikisweeting/archivebox:$NEW_VERSION \
               -t docker.pkg.github.com/pirate/archivebox/archivebox:latest \
               -t docker.pkg.github.com/pirate/archivebox/archivebox:$NEW_VERSION

echo "[^] Uploading docker image"
# docker login --username=nikisweeting
# docker login docker.pkg.github.com --username=pirate
docker push docker.io/nikisweeting/archivebox
docker push docker.pkg.github.com/pirate/archivebox/archivebox

echo "[√] Done. Published version v$NEW_VERSION"
