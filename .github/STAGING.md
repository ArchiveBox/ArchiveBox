# Stable releases require live dev acceptance

The order is **dev CI → dev image publication → automatic Cabbage deployment →
real capture and browser acceptance → stable publication**. Never
substitute a published PyPI wheel, healthy container, or local build for this
acceptance. The release workflow blocks *before* a stable upload unless Cabbage
has successful evidence from `staging-acceptance.yml` matching all tracked
source and dependency pins. Only ArchiveBox's own version fields may change
between dev and stable.

The staging workflow observes the existing image watcher; it cannot deploy or
restart the application. On Cabbage, install `bin/staging-acceptance-host.sh`
as root-owned mode 0755 `/usr/local/sbin/archivebox-staging-acceptance`. Its hash
is checked against the candidate. A dedicated SSH key must use
`restrict,command="/usr/local/sbin/archivebox-staging-acceptance"` in authorized
keys. It accepts only `inspect <source-sha>` and `capture <source-sha>`; it cannot
run caller-provided commands or archive arbitrary URLs.

The `staging` GitHub environment is restricted to dev/main branches. It contains
`STAGING_SSH_KEY` and `STAGING_KNOWN_HOSTS`, with independently verified host keys.
Only trusted release events use the private ugNAS runner route. Never expose
these credentials to PR jobs or copy an operator's existing root key.

Acceptance creates one tagged background crawl per source through the normal
add/runner path, enabling every snapshot extractor, including TLSNotary. It
checks installed pins, completed outputs and their files, unexpected/missing
plugin results, host OOM kills, and real rendered snapshot pages. For this
release, the explicitly accepted TLSNotary failures and exact missing-Claude-auth
diagnostics are retained in the report's `limitations` list; they do not disable
those plugins or excuse missing/truncated successful outputs. Remove the
TLSNotary exception when its follow-up fix ships. Logs, result inventories and
screenshots are retained as Actions artifacts. Other failures remain
failures; do not publish a success deployment record to bypass them. No code
mounts are allowed. The Cabbage job must pass before its record authorizes a
stable upload. Queued capture progress is polled; failed tests are not retried.

Browser acceptance follows the default WACZ viewer into the captured document,
matching its replay base and original URL and checking that its body is visible
and contains substantial text. An attached viewer iframe can still be
`about:blank`, so its presence alone cannot prove replay works. Extracted display
titles and the captured document's `<title>` may legitimately differ; neither
title equality nor output thumbnails substitute for checking the actual page.
