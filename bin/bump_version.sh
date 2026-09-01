#!/usr/bin/env bash

set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ "$#" -ne 1 ]]; then
    echo "Usage: $0 <version>" >&2
    exit 2
fi

uv run --no-cache --no-project python - "$1" <<'PY'
from pathlib import Path
import json
import re
import sys
import tomllib

version = sys.argv[1]
if not re.fullmatch(r'\d+\.\d+\.\d+(?:-?rc\d*)?', version):
    raise SystemExit(f'Unsupported version format: {version}')

pyproject = Path('pyproject.toml')
text = pyproject.read_text()
match = re.search(r'^version = "([^"]+)"$', text, re.MULTILINE)
if not match:
    raise SystemExit('Failed to find version in pyproject.toml')
def parse(value):
    base, _, rc = value.replace('-rc', 'rc').partition('rc')
    major, minor, patch = map(int, base.split('.'))
    return major, minor, patch, 0 if 'rc' in value else 1, int(rc or 0)
if parse(version) <= parse(match.group(1)):
    raise SystemExit(f'New version {version} must be greater than {match.group(1)}')
updated, count = re.subn(r'^version = "[^"]+"$', f'version = "{version}"', text, count=1, flags=re.MULTILINE)
if count != 1:
    raise SystemExit('Failed to update version in pyproject.toml')
updated, count = re.subn(
    r'^current_version = "v[^"]+"$',
    f'current_version = "v{version}"',
    updated,
    count=1,
    flags=re.MULTILINE,
)
if count != 1:
    raise SystemExit('Failed to update tool.bumpver.current_version in pyproject.toml')
pyproject.write_text(updated)

package_path = Path('etc/package.json')
package = json.loads(package_path.read_text())
package['version'] = version
package_path.write_text(json.dumps(package, indent=2) + '\n')

lock_path = Path('uv.lock')
lock, count = re.subn(
    r'(?m)^(name = "archivebox"\nversion = ")[^"]+("$)',
    rf'\g<1>{version}\2',
    lock_path.read_text(),
    count=1,
)
if count != 1:
    raise SystemExit('Failed to update ArchiveBox version in uv.lock')
lock_path.write_text(lock)
locked = tomllib.loads(lock)
if next(package['version'] for package in locked['package'] if package['name'] == 'archivebox') != version:
    raise SystemExit('Updated ArchiveBox lock version does not match the requested version')
print(version)
PY
