#!/usr/bin/env bash
# Root-owned SSH forced command on our test hosts. Never evaluate the caller's
# input as shell, accept a URL, or permit deployment/container-control commands.
set -Eeuo pipefail
if [[ ! "${SSH_ORIGINAL_COMMAND:-}" =~ ^(inspect|capture)\ ([0-9a-f]{40})$ ]]; then
    echo 'Only inspect/capture followed by an exact source SHA is allowed.' >&2
    exit 64
fi
operation="${BASH_REMATCH[1]}"
source_sha="${BASH_REMATCH[2]}"
case "$(hostname -s)" in
    cabbage) container=archiveboxdemo-archivebox-1 ;;
    brussel) container=archivebox-archivebox-1 ;;
    *) echo 'Not an ArchiveBox staging host.' >&2; exit 64 ;;
esac
revision="$(docker inspect "$container" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
if [[ "$revision" != "$source_sha" ]]; then
    echo "Awaiting automatic deployment: running $revision, expected $source_sha" >&2
    exit 75
fi
test "$(docker inspect "$container" --format '{{.State.Health.Status}}')" = healthy
# A source bind mount would invalidate the immutable image's provenance.
while IFS= read -r destination; do
    case "$destination" in
        /app|/app/*|/venv|/venv/*|/opt/archivebox|/opt/archivebox/*)
            echo "Refusing code mount at $destination" >&2; exit 1 ;;
    esac
done < <(docker inspect "$container" --format '{{range .Mounts}}{{println .Destination}}{{end}}')

if [[ "$operation" == inspect ]]; then
    helper_hash="$(sha256sum "$0" | cut -d ' ' -f 1)"
    docker inspect "$container" --format "{\"helper_sha256\":\"$helper_hash\",\"container_id\":{{json .Id}},\"image_id\":{{json .Image}},\"revision\":{{json (index .Config.Labels \"org.opencontainers.image.revision\")}},\"version\":{{json (index .Config.Labels \"org.opencontainers.image.version\")}},\"health\":{{json .State.Health.Status}}}"
    exit 0
fi

# Persist the start of this candidate's real acceptance flow. Repeated status
# requests observe the same crawl instead of repeatedly adding test data.
install -d -m 700 /var/lib/archivebox-staging
exec 9>/var/lib/archivebox-staging/acceptance.lock
flock -x 9
start_file="/var/lib/archivebox-staging/$source_sha.started"
if [[ ! -e "$start_file" ]]; then date -u +%FT%TZ > "$start_file"; fi
since="$(cat "$start_file")"
# Read separately so a journal failure cannot masquerade as "no OOM found"
# through the conditional pipeline's nonzero exit status.
kernel_log="$(journalctl -k --since "$since" --no-pager)"
if grep 'Out of memory: Killed process' <<< "$kernel_log" >/dev/null; then
    echo 'Staging acceptance failed: the host had an OOM kill during this candidate test.' >&2
    exit 1
fi

script="$(cat <<'PY'
import json
import os
from pathlib import Path
from archivebox.crawls.models import Crawl
from archivebox.cli.archivebox_add import add
from archivebox.config import VERSION
from archivebox.core.routes_util import build_snapshot_detail_url
from archivebox.plugins.discovery import get_plugin_catalog
from importlib.metadata import version

sha = os.environ['ACCEPTANCE_SHA']
tag = f'release-acceptance-{sha}'
urls = ['https://docs.sweeting.me/s/cookie-dilemma', 'https://sweeting.me/']
capture_plugins = [plugin for plugin in get_plugin_catalog().values() if any(hook.event == 'Snapshot' for hook in plugin.hooks)]
capture_config = {'PERMISSIONS': 'public', **{plugin.enabled_key: True for plugin in capture_plugins}}
crawls = list(Crawl.objects.filter(tags_str=tag).order_by('created_at'))
if not crawls:
    # Normal add/runner flow with every snapshot extractor enabled, including
    # opt-in TLSNotary. Never select a subset or steal the server runner's lease.
    crawl, _ = add(urls=urls, depth=0, tag=tag, bg=True, persona='ReleaseAcceptance', config=capture_config)
    crawls = [crawl]
if len(crawls) != 1:
    raise RuntimeError('Expected one acceptance crawl for this source')
crawl = crawls[0]
snapshots = list(crawl.snapshot_set.all())
report = {
    'source_sha': sha, 'version': VERSION, 'crawl_id': str(crawl.pk),
    'pins': {p: version(p) for p in ('abx-dl', 'abx-plugins', 'abxbus', 'abxpkg')},
    'status': 'pending', 'snapshots': [], 'errors': [],
    'enabled_capture_plugins': sorted(plugin.name for plugin in capture_plugins),
}
complete = crawl.status == 'sealed' and len(snapshots) == len(urls) and all(s.status == 'sealed' for s in snapshots)
for snapshot in snapshots:
    results = list(snapshot.archiveresult_set.all())
    statuses = {}
    for result in results:
        statuses.setdefault(result.plugin, []).append(str(result.status))
    report['snapshots'].append({'id': str(snapshot.pk), 'url': snapshot.url, 'replay_url': build_snapshot_detail_url(snapshot.archive_path_from_db), 'status': snapshot.status, 'plugins': statuses})
    if not complete:
        continue
    # Real stored outputs, not status labels alone. Missing core capture formats
    # and failed extractors remain visible failures for investigation.
    for plugin in ('screenshot', 'pdf', 'singlefile', 'archivewebpage', 'readability', 'defuddle', 'hashes', 'tlsnotary'):
        if 'succeeded' not in statuses.get(plugin, []):
            report['errors'].append(f'{snapshot.pk}: {plugin} did not succeed')
    for plugin in capture_plugins:
        if plugin.name not in statuses:
            report['errors'].append(f'{snapshot.pk}: {plugin.name} never reported an output status')
    for result in results:
        if result.status == 'failed':
            report['errors'].append(f'{snapshot.pk}: {result.plugin}: {result.output_str}')
        if result.status != 'succeeded':
            continue
        for relative, metadata in (result.output_files or {}).items():
            if result.plugin == 'chrome':
                # Chrome's live session handles are intentionally removed at
                # crawl teardown; they are not archived replay artifacts.
                continue
            base = Path(snapshot.output_dir) if metadata.get('root_relative') else Path(snapshot.output_dir) / result.plugin
            output = base / relative
            if not output.is_file() or output.stat().st_size != metadata.get('size'):
                report['errors'].append(f'{snapshot.pk}: missing or truncated {result.plugin}/{relative}')
if complete:
    report['status'] = 'failed' if report['errors'] else 'passed'
print('STAGING_REPORT=' + json.dumps(report, default=str))
PY
)"
docker exec -e "ACCEPTANCE_SHA=$source_sha" "$container" archivebox shell -c "$script"
