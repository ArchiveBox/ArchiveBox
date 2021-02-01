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
cd "$REPO_DIR"
source "$REPO_DIR/.venv/bin/activate"


# apt install python3 python3-all python3-dev
# pip install '.[dev]'


echo "[^] Uploading to test.pypi.org"
python3 -m twine upload --repository testpypi pip_dist/archivebox-${VERSION}*.{whl,tar.gz}

echo "[^] Uploading to pypi.org"
python3 -m twine upload --repository pypi pip_dist/archivebox-${VERSION}*.{whl,tar.gz}
