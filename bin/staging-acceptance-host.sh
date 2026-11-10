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
health="$(docker inspect "$container" --format '{{.State.Health.Status}}')"
case "$health" in
    healthy) ;;
    starting)
        # The watcher has installed the candidate, but init/migrations and the
        # first healthcheck can still be running. This is deployment observation,
        # not acceptance: the caller only waits before its first healthy inspect.
        echo "Awaiting automatic deployment: candidate health is starting" >&2
        exit 75
        ;;
    *) echo "Staging candidate health is $health, expected healthy" >&2; exit 1 ;;
esac
# A source bind mount would invalidate the immutable image's provenance.
while IFS= read -r destination; do
    case "$destination" in
        /app|/app/*|/venv|/venv/*|/opt/archivebox|/opt/archivebox/*)
            echo "Refusing code mount at $destination" >&2; exit 1 ;;
    esac
done < <(docker inspect "$container" --format '{{range .Mounts}}{{println .Destination}}{{end}}')

if [[ "$operation" == inspect ]]; then
    helper_hash="$(sha256sum "$0" | cut -d ' ' -f 1)"
    docker inspect "$container" --format "{\"helper_sha256\":\"$helper_hash\",\"container_id\":{{json .Id}},\"image_id\":{{json .Image}},\"revision\":{{json (index .Config.Labels \"org.opencontainers.image.revision\")}},\"version\":{{json (index .Config.Labels \"org.opencontainers.image.version\")}},\"abx_dl_image\":{{json (index .Config.Labels \"io.archivebox.abx-dl.image\")}},\"health\":{{json .State.Health.Status}}}"
    exit 0
fi

# Observe the existing workload after this candidate is ready. Acceptance must
# never add production captures; daily feeds and user backlogs supply the work.
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
from archivebox.core.models import Snapshot
from archivebox.core.permissions import public_snapshots_queryset
from django.utils.dateparse import parse_datetime
from archivebox.config import VERSION
from archivebox.core.routes_util import build_snapshot_detail_url
from archivebox.plugins.discovery import get_enabled_plugins, get_plugin_catalog
from importlib.metadata import version

sha = os.environ['ACCEPTANCE_SHA']
since = parse_datetime(os.environ['ACCEPTANCE_SINCE'])
if since is None:
    raise ValueError('Missing candidate observation start time')
catalog = get_plugin_catalog()
enabled_plugins = get_enabled_plugins()
capture_plugins = [plugin for plugin in catalog.values() if plugin.name in enabled_plugins and any(hook.event == 'Snapshot' for hook in plugin.hooks)]

def accepted_limitation(plugin, status, output_str):
    # Keep this release waiver limited to the three observed, exact Claude
    # missing-auth diagnostics and explicit TLSNotary failures. All such
    # outcomes remain visible in STAGING_REPORT.limitations.
    claude_auth_failures = {
        'claudechrome': 'ANTHROPIC_API_KEY not set',
        'claudecodeextract': 'Claude Code auth not set',
        'claudecodecleanup': 'Claude Code auth not set',
    }
    return status == 'failed' and (
        plugin == 'tlsnotary' or output_str == claude_auth_failures.get(plugin)
    )

# Take the first two public captures completed by the existing workload after
# observation began. Do not pick only successful plugins: failures on these
# captures must fail acceptance instead of silently selecting easier pages.
# Ordered completion timestamps keep the sample stable across polling and the
# final browser check. Exclude the obsolete synthetic acceptance crawls.
snapshots = list(public_snapshots_queryset(Snapshot.objects.filter(
    status='sealed', downloaded_at__gte=since,
)).exclude(crawl__tags_str__startswith='release-acceptance-').order_by('downloaded_at', 'id')[:2])
report = {
    'source_sha': sha, 'version': VERSION, 'crawl_id': str(snapshots[0].crawl_id) if snapshots else None,
    'pins': {p: version(p) for p in ('abx-dl', 'abx-plugins', 'abxbus', 'abxpkg')},
    'status': 'pending', 'snapshots': [], 'errors': [], 'limitations': [],
    'enabled_capture_plugins': sorted(plugin.name for plugin in capture_plugins),
    'disabled_plugins': sorted(set(catalog) - set(enabled_plugins)),
}
complete = len(snapshots) == 2
for snapshot in snapshots:
    results = list(snapshot.archiveresult_set.all())
    statuses = {}
    for result in results:
        statuses.setdefault(result.plugin, []).append(str(result.status))
    report['snapshots'].append({'id': str(snapshot.pk), 'url': snapshot.url, 'replay_url': build_snapshot_detail_url(snapshot.archive_path_from_db), 'status': snapshot.status, 'plugins': statuses})
    # Real stored outputs, not status labels alone. Missing core capture formats
    # and failed extractors remain visible failures for investigation.
    for plugin in ('screenshot', 'pdf', 'singlefile', 'archivewebpage', 'readability', 'defuddle', 'hashes'):
        if 'succeeded' not in statuses.get(plugin, []):
            report['errors'].append(f'{snapshot.pk}: {plugin} did not succeed')
    for plugin in capture_plugins:
        if plugin.name not in statuses:
            report['errors'].append(f'{snapshot.pk}: {plugin.name} never reported an output status')
    for result in results:
        if result.status == 'failed':
            message = f'{snapshot.pk}: {result.plugin}: {result.output_str}'
            if accepted_limitation(result.plugin, str(result.status), result.output_str or ''):
                report['limitations'].append(message)
            else:
                report['errors'].append(message)
            continue
        if result.plugin == 'tlsnotary' and result.status != 'succeeded':
            report['errors'].append(f'{snapshot.pk}: tlsnotary reported unexpected status {result.status}')
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
docker exec -e "ACCEPTANCE_SHA=$source_sha" -e "ACCEPTANCE_SINCE=$since" "$container" archivebox shell -c "$script"
