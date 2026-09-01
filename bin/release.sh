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

pypi_release_json() {
    "$CURL_BINARY" -fsSL \
        -H 'Cache-Control: no-cache, no-store, max-age=0' -H 'Pragma: no-cache' \
        "https://pypi.org/pypi/${PYPI_PACKAGE}/$1/json?cache_bust=$(date +%s)-${RANDOM}"
}

VERSION="$($UV_BINARY run --no-cache --no-project python - <<'PY'
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
RELEASE_BRANCH="${RELEASE_BRANCH:-dev}"
IS_RC=false
if [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+rc[0-9]+$ ]]; then
    IS_RC=true
fi

case "$RELEASE_BRANCH" in
    dev|main) ;;
    *)
        echo "Refusing to publish ArchiveBox release $VERSION from unsupported branch $RELEASE_BRANCH; only archivebox:dev and archivebox:main may publish" >&2
        exit 1
        ;;
esac

if [[ "$RELEASE_BRANCH" != main && "$IS_RC" != true ]]; then
    echo "Refusing to publish ArchiveBox release $VERSION from $RELEASE_BRANCH; only archivebox:main may publish non-prerelease versions" >&2
    exit 1
fi

PYPI_VERSIONS="$($CURL_BINARY -fsSL "https://pypi.org/pypi/${PYPI_PACKAGE}/json" | $JQ_BINARY -r '.releases | keys[]')"
GIT_TAGS="$($GIT_BINARY ls-remote --tags origin "refs/tags/${TAG_PREFIX}*" | while read -r _ ref; do ref="${ref#refs/tags/}"; ref="${ref%\^\{\}}"; echo "$ref"; done | sort -u)"
LATEST="$(PYPI_VERSIONS="$PYPI_VERSIONS" GIT_TAGS="$GIT_TAGS" TAG_PREFIX="$TAG_PREFIX" $UV_BINARY run --no-cache --no-project python - <<'PY'
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
versions.update(tag[len(prefix):] if tag.startswith(prefix) else tag for tag in os.environ['GIT_TAGS'].splitlines())
versions = [version for version in versions if parse(version)[0] >= 0]
print(max(versions, key=parse) if versions else '')
PY
)"
if [[ -n "$LATEST" ]]; then
    ORDER="$(CURRENT="$VERSION" LATEST="$LATEST" $UV_BINARY run --no-cache --no-project python - <<'PY'
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
$GIT_BINARY fetch --quiet --no-tags origin "+refs/heads/${RELEASE_BRANCH}:refs/remotes/origin/${RELEASE_BRANCH}"
BRANCH_HEAD="$($GIT_BINARY rev-parse "refs/remotes/origin/${RELEASE_BRANCH}")"
if [[ "$RELEASE_SHA" != "$BRANCH_HEAD" ]]; then
    echo "Skipping ArchiveBox release $VERSION from obsolete CI SHA $RELEASE_SHA; current origin/${RELEASE_BRANCH} is $BRANCH_HEAD" >&2
    exit 0
fi

TAG_TARGET="$($GIT_BINARY ls-remote origin "refs/tags/${TAG}^{}")"
TAG_TARGET="${TAG_TARGET%%[[:space:]]*}"
if [[ -z "$TAG_TARGET" ]]; then
    TAG_TARGET="$($GIT_BINARY ls-remote origin "refs/tags/${TAG}")"
    TAG_TARGET="${TAG_TARGET%%[[:space:]]*}"
fi

if [[ -n "$TAG_TARGET" && "$TAG_TARGET" != "$RELEASE_SHA" ]]; then
    $GIT_BINARY merge-base --is-ancestor "$TAG_TARGET" "refs/remotes/origin/${RELEASE_BRANCH}" || {
        echo "Existing tag $TAG is not on $RELEASE_BRANCH" >&2
        exit 1
    }
    PYPI_URLS="$(pypi_release_json "$VERSION" | $JQ_BINARY -c '.urls')"
    PYPI_URLS="$PYPI_URLS" VERSION="$VERSION" $UV_BINARY run --no-cache --no-project python - <<'PY'
import json
import os
import re

version = os.environ["VERSION"]
expected_names = {
    f"archivebox-{version}-py3-none-any.whl",
    f"archivebox-{version}.tar.gz",
}
published_files = json.loads(os.environ["PYPI_URLS"])
published = {item["filename"]: item["digests"].get("sha256", "") for item in published_files}
if set(published) != expected_names:
    raise SystemExit(f"PyPI release {version} does not contain the exact wheel and sdist")
for filename, digest in published.items():
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SystemExit(f"PyPI release {version} has an invalid sha256 for {filename}")
PY
    if [[ "$IS_RC" == true ]]; then
        # Never create GitHub Releases for automated rc builds. GitHub emails
        # every subscribed user for release publications, and dev can cut many
        # rc builds per day while packaging catches up.
        echo "${PYPI_PACKAGE} ${VERSION} is already tagged and published to PyPI from ${TAG_TARGET}; skipping GitHub Release for rc version"
        exit 0
    fi
    RELEASE_JSON="$($GH_BINARY release view "$TAG" --repo "$SLUG" --json assets,isDraft,isPrerelease,tagName)"
    RELEASE_JSON="$RELEASE_JSON" VERSION="$VERSION" TAG="$TAG" $UV_BINARY run --no-cache --no-project python - <<'PY'
import json
import os
import re

version = os.environ["VERSION"]
release = json.loads(os.environ["RELEASE_JSON"])
expected_names = {
    "COMMIT_SHA",
    "SHA256SUMS",
    f"archivebox-{version}-py3-none-any.whl",
    f"archivebox-{version}.tar.gz",
}
assets = release["assets"]
published = {asset["name"]: asset.get("digest", "") for asset in assets}
if release["tagName"] != os.environ["TAG"]:
    raise SystemExit("GitHub release tag does not match the source version")
if release["isDraft"] or release["isPrerelease"]:
    raise SystemExit("GitHub release draft/prerelease metadata is incorrect")
if len(published) != len(assets) or set(published) != expected_names:
    raise SystemExit("GitHub release asset set is incomplete or contains extras")
for filename, digest in published.items():
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise SystemExit(f"GitHub release has an invalid digest for {filename}")
PY
    echo "${PYPI_PACKAGE} ${VERSION} is already fully released from ${TAG_TARGET}"
    exit 0
fi

[[ "$(<"$RELEASE_DISTRIBUTIONS_DIR/COMMIT_SHA")" == "$RELEASE_SHA" ]]
$UV_BINARY run --no-cache --no-project python - "$RELEASE_DISTRIBUTIONS_DIR" "$VERSION" <<'PY'
from hashlib import sha256
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
version = sys.argv[2]
expected_names = {
    "COMMIT_SHA",
    f"archivebox-{version}-py3-none-any.whl",
    f"archivebox-{version}.tar.gz",
}
files = {path.name for path in root.iterdir() if path.is_file()}
if files != expected_names | {"SHA256SUMS"}:
    raise SystemExit(f"Unexpected tested distribution set: {sorted(files)}")

manifest = {}
for line in (root / 'SHA256SUMS').read_text().splitlines():
    expected, separator, filename = line.partition('  ')
    if (
        not separator
        or not re.fullmatch(r'[0-9a-f]{64}', expected)
        or Path(filename).name != filename
    ):
        raise SystemExit(f'Invalid SHA256SUMS line: {line!r}')
    if filename in manifest:
        raise SystemExit(f'Duplicate SHA256SUMS entry: {filename}')
    manifest[filename] = expected

if set(manifest) != expected_names:
    raise SystemExit(f'SHA256SUMS names the wrong files: {sorted(manifest)}')

for filename, expected in manifest.items():
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
[[ "${WHEELS[0]##*/}" == "archivebox-${VERSION}-py3-none-any.whl" ]]
[[ "${SDISTS[0]##*/}" == archivebox-${VERSION}.tar.gz ]]
[[ -z "$TAG_TARGET" || "$TAG_TARGET" == "$RELEASE_SHA" ]] || {
    echo "$TAG points to $TAG_TARGET, not $RELEASE_SHA" >&2
    exit 1
}

PYPI_URLS="$(pypi_release_json "$VERSION" | $JQ_BINARY -c '.urls')" || PYPI_URLS='[]'
PYPI_STATUS_OUTPUT="$(PYPI_URLS="$PYPI_URLS" RELEASE_DISTRIBUTIONS_DIR="$RELEASE_DISTRIBUTIONS_DIR" VERSION="$VERSION" $UV_BINARY run --no-cache --no-project python - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["RELEASE_DISTRIBUTIONS_DIR"])
version = os.environ["VERSION"]
expected_names = {
    f"archivebox-{version}-py3-none-any.whl",
    f"archivebox-{version}.tar.gz",
}
manifest = {}
for line in (root / "SHA256SUMS").read_text().splitlines():
    digest, filename = line.split(maxsplit=1)
    if filename in expected_names:
        manifest[filename] = digest
if set(manifest) != expected_names:
    raise SystemExit("Tested manifest does not contain the exact PyPI artifacts")

published_files = json.loads(os.environ["PYPI_URLS"])
if not published_files:
    print("absent")
    for filename in sorted(expected_names):
        print(filename)
    raise SystemExit(0)
published = {item["filename"]: item["digests"]["sha256"] for item in published_files}
if len(published) != len(published_files) or not set(published).issubset(expected_names):
    raise SystemExit("PyPI release contains duplicate or unexpected distributions")
for filename, digest in published.items():
    if manifest[filename] != digest:
        raise SystemExit(f"PyPI digest mismatch for {filename}")

missing = sorted(expected_names - set(published))
print("partial" if missing else "complete")
for filename in missing:
    print(filename)
PY
)"
mapfile -t PYPI_STATUS_LINES <<< "$PYPI_STATUS_OUTPUT"
PYPI_STATE="${PYPI_STATUS_LINES[0]}"
PYPI_MISSING=("${PYPI_STATUS_LINES[@]:1}")
[[ "$PYPI_STATE" == absent || "$PYPI_STATE" == partial || "$PYPI_STATE" == complete ]]

GITHUB_EXISTS=false
if [[ "$IS_RC" != true ]] && $GH_BINARY release view "$TAG" --repo "$SLUG" >/dev/null 2>&1; then
    GITHUB_EXISTS=true
fi
if [[ ( "$PYPI_STATE" != absent || "$GITHUB_EXISTS" == true ) && "$TAG_TARGET" != "$RELEASE_SHA" ]]; then
    echo "Cannot recover partial release $VERSION without an exact-SHA tag" >&2
    exit 1
fi

if [[ -z "$TAG_TARGET" ]]; then
    $GIT_BINARY tag "$TAG" "$RELEASE_SHA"
    $GIT_BINARY push origin "refs/tags/${TAG}"
    TAG_TARGET="$RELEASE_SHA"
fi

if [[ "$PYPI_STATE" != complete ]]; then
    PYPI_ARTIFACTS=()
    for filename in "${PYPI_MISSING[@]}"; do
        [[ "$filename" == "${filename##*/}" && -f "$RELEASE_DISTRIBUTIONS_DIR/$filename" ]]
        PYPI_ARTIFACTS+=("$RELEASE_DISTRIBUTIONS_DIR/$filename")
    done
    [[ "${#PYPI_ARTIFACTS[@]}" -gt 0 ]]
    $UV_BINARY publish --no-cache --trusted-publishing always "${PYPI_ARTIFACTS[@]}"
fi

if [[ "$IS_RC" == true ]]; then
    # Never create GitHub Releases for automated rc builds. GitHub emails
    # every subscribed user for release publications, and dev can cut many
    # rc builds per day while packaging catches up.
    echo "Released ${PYPI_PACKAGE} ${VERSION} from ${RELEASE_SHA} using CI run ${CI_RUN_ID:-unknown}; skipped GitHub Release for rc version"
    exit 0
fi

if [[ "$GITHUB_EXISTS" == false ]]; then
    $GH_BINARY release create "$TAG" --repo "$SLUG" --verify-tag \
        --title "$TAG" --generate-notes
fi

$GH_BINARY release upload "$TAG" --repo "$SLUG" \
    "$RELEASE_DISTRIBUTIONS_DIR/COMMIT_SHA" \
    "${WHEELS[0]}" \
    "${SDISTS[0]}" \
    "$RELEASE_DISTRIBUTIONS_DIR/SHA256SUMS" \
    --clobber

RELEASE_JSON="$($GH_BINARY release view "$TAG" --repo "$SLUG" --json assets,tagName)"
RELEASE_JSON="$RELEASE_JSON" RELEASE_DISTRIBUTIONS_DIR="$RELEASE_DISTRIBUTIONS_DIR" VERSION="$VERSION" TAG="$TAG" $UV_BINARY run --no-cache --no-project python - <<'PY'
from hashlib import sha256
from pathlib import Path
import json
import os

root = Path(os.environ["RELEASE_DISTRIBUTIONS_DIR"])
version = os.environ["VERSION"]
release = json.loads(os.environ["RELEASE_JSON"])
expected_names = {
    "COMMIT_SHA",
    "SHA256SUMS",
    f"archivebox-{version}-py3-none-any.whl",
    f"archivebox-{version}.tar.gz",
}
if release["tagName"] != os.environ["TAG"]:
    raise SystemExit("GitHub release tag does not match the source version")

assets = release["assets"]
published = {asset["name"]: asset.get("digest", "") for asset in assets}
if len(published) != len(assets) or set(published) != expected_names:
    raise SystemExit("GitHub release asset set is incomplete or contains extras")

manifest = {}
for line in (root / "SHA256SUMS").read_text().splitlines():
    digest, filename = line.split(maxsplit=1)
    manifest[filename] = digest
for filename in expected_names:
    local_digest = sha256((root / filename).read_bytes()).hexdigest()
    if filename != "SHA256SUMS" and manifest.get(filename) != local_digest:
        raise SystemExit(f"Local manifest mismatch for {filename}")
    if published[filename] != f"sha256:{local_digest}":
        raise SystemExit(f"GitHub release digest mismatch for {filename}")
PY

echo "Released ${PYPI_PACKAGE} ${VERSION} from ${RELEASE_SHA} using CI run ${CI_RUN_ID:-unknown}"
