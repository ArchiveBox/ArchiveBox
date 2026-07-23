#!/usr/bin/env bash
set -Eeuo pipefail

[[ -z "$(git status --short -- uv.lock)" ]]
uv lock
if git diff --quiet -- uv.lock; then
    echo "uv lock did not record the bumped ArchiveBox version" >&2
    exit 1
fi
git add uv.lock
