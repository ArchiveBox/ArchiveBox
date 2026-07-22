#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
[[ "$SCRIPT_DIR" != "${BASH_SOURCE[0]}" ]] || SCRIPT_DIR=.
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

for variable in UV_BINARY GH_BINARY GIT_BINARY JQ_BINARY CURL_BINARY RELEASE_SHA RELEASE_DISTRIBUTIONS_DIR; do
    value="${!variable:-}"
    [[ -n "$value" ]] || { echo "$variable must be set" >&2; exit 1; }
done
for variable in UV_BINARY GH_BINARY GIT_BINARY JQ_BINARY CURL_BINARY; do
    [[ -x "${!variable}" ]] || { echo "$variable is not executable: ${!variable}" >&2; exit 1; }
done

TAG_PREFIX=v
PYPI_PACKAGE=archivebox

VERSION="$($UV_BINARY run --no-project python - <<'PY'
from pathlib import Path
import json
import re

match = re.search(r'^version = "([^"]+)"$', Path('pyproject.toml').read_text(), re.MULTILINE)
if not match:
    raise SystemExit('Failed to find version in pyproject.toml')
version = match.group(1)
package_version = json.loads(Path('etc/package.json').read_text())['version']
if version != package_version:
    raise SystemExit(f'Version mismatch: pyproject.toml={version}, etc/package.json={package_version}')
print(version)
PY
)"
SLUG="$($GH_BINARY repo view --json nameWithOwner --jq .nameWithOwner)"
TAG="${TAG_PREFIX}${VERSION}"

PYPI_VERSIONS="$($CURL_BINARY -fsSL "https://pypi.org/pypi/${PYPI_PACKAGE}/json" | $JQ_BINARY -r '.releases | keys[]')"
GITHUB_TAGS="$($GH_BINARY api "repos/${SLUG}/releases?per_page=100" --jq '.[].tag_name')"
LATEST="$(PYPI_VERSIONS="$PYPI_VERSIONS" GITHUB_TAGS="$GITHUB_TAGS" TAG_PREFIX="$TAG_PREFIX" $UV_BINARY run --no-project python - <<'PY'
import os
import re

def parse(version):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-?rc(\d*))?', version)
    if not match:
        return -1, -1, -1, -1, -1
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), 0 if 'rc' in version else 1, int(rc or 0)

versions = set(os.environ['PYPI_VERSIONS'].splitlines())
prefix = os.environ['TAG_PREFIX']
versions.update(tag[len(prefix):] if tag.startswith(prefix) else tag for tag in os.environ['GITHUB_TAGS'].splitlines())
versions = [version for version in versions if parse(version)[0] >= 0]
print(max(versions, key=parse) if versions else '')
PY
)"
if [[ -n "$LATEST" ]]; then
    ORDER="$(CURRENT="$VERSION" LATEST="$LATEST" $UV_BINARY run --no-project python - <<'PY'
import os
import re

def parse(version):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-?rc(\d*))?', version)
    if not match:
        raise SystemExit(f'Unsupported version format: {version}')
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), 0 if 'rc' in version else 1, int(rc or 0)

print('lt' if parse(os.environ['CURRENT']) < parse(os.environ['LATEST']) else 'ok')
PY
)"
    [[ "$ORDER" != lt ]] || { echo "Source version $VERSION is behind published version $LATEST" >&2; exit 1; }
fi

[[ "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$($GIT_BINARY rev-parse HEAD)" == "$RELEASE_SHA" ]]
[[ -z "$($GIT_BINARY status --short)" ]]
$GIT_BINARY fetch --quiet --no-tags origin "+refs/heads/${RELEASE_BRANCH:-dev}:refs/remotes/origin/${RELEASE_BRANCH:-dev}"
$GIT_BINARY merge-base --is-ancestor "$RELEASE_SHA" "refs/remotes/origin/${RELEASE_BRANCH:-dev}"

[[ "$(<"$RELEASE_DISTRIBUTIONS_DIR/COMMIT_SHA")" == "$RELEASE_SHA" ]]
$UV_BINARY run --no-project python - "$RELEASE_DISTRIBUTIONS_DIR" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

root = Path(sys.argv[1])
for line in (root / 'SHA256SUMS').read_text().splitlines():
    expected, separator, filename = line.partition('  ')
    if not separator or len(expected) != 64:
        raise SystemExit(f'Invalid SHA256SUMS line: {line!r}')
    artifact = root / filename
    actual = sha256(artifact.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f'Checksum mismatch for {artifact}: expected {expected}, got {actual}')
PY
shopt -s nullglob
WHEELS=("$RELEASE_DISTRIBUTIONS_DIR"/archivebox-*.whl)
SDISTS=("$RELEASE_DISTRIBUTIONS_DIR"/archivebox-*.tar.gz)
[[ "${#WHEELS[@]}" -eq 1 ]]
[[ "${#SDISTS[@]}" -eq 1 ]]
[[ "${WHEELS[0]##*/}" == archivebox-${VERSION}-*.whl ]]
[[ "${SDISTS[0]##*/}" == archivebox-${VERSION}.tar.gz ]]

TAG_TARGET="$($GIT_BINARY ls-remote origin "refs/tags/${TAG}^{}")"
TAG_TARGET="${TAG_TARGET%%[[:space:]]*}"
if [[ -z "$TAG_TARGET" ]]; then
    TAG_TARGET="$($GIT_BINARY ls-remote origin "refs/tags/${TAG}")"
    TAG_TARGET="${TAG_TARGET%%[[:space:]]*}"
fi
[[ -z "$TAG_TARGET" || "$TAG_TARGET" == "$RELEASE_SHA" ]] || {
    echo "$TAG points to $TAG_TARGET, not $RELEASE_SHA" >&2
    exit 1
}

PYPI_EXISTS=false
GITHUB_EXISTS=false
$CURL_BINARY -fsSL "https://pypi.org/pypi/${PYPI_PACKAGE}/${VERSION}/json" >/dev/null 2>&1 && PYPI_EXISTS=true
$GH_BINARY release view "$TAG" --repo "$SLUG" >/dev/null 2>&1 && GITHUB_EXISTS=true
if [[ ( "$PYPI_EXISTS" == true || "$GITHUB_EXISTS" == true ) && "$TAG_TARGET" != "$RELEASE_SHA" ]]; then
    echo "Cannot recover partial release $VERSION without an exact-SHA tag" >&2
    exit 1
fi

if [[ -z "$TAG_TARGET" ]]; then
    $GIT_BINARY tag "$TAG" "$RELEASE_SHA"
    $GIT_BINARY push origin "refs/tags/${TAG}"
fi

if [[ "$PYPI_EXISTS" == false ]]; then
    $UV_BINARY publish --trusted-publishing always "${WHEELS[@]}" "${SDISTS[@]}"
fi

if [[ "$GITHUB_EXISTS" == false ]]; then
    RELEASE_ARGS=()
    [[ "$VERSION" == *rc* ]] && RELEASE_ARGS+=(--prerelease)
    $GH_BINARY release create "$TAG" --repo "$SLUG" --verify-tag \
        --title "$TAG" --generate-notes "${RELEASE_ARGS[@]}"
fi

echo "Released ${PYPI_PACKAGE} ${VERSION} from ${RELEASE_SHA} using CI run ${CI_RUN_ID:-unknown}"
