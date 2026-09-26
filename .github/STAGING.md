# Stable releases require live dev acceptance

The order is **dev CI → dev image publication → automatic Cabbage and DigestBox
deployment → real capture and browser acceptance → stable publication**. Never
substitute a published PyPI wheel, healthy container, or local build for this
acceptance. The release workflow blocks *before* a stable upload unless both
environments have successful evidence from `staging-acceptance.yml` matching all
tracked source and dependency pins. Only ArchiveBox's own version fields may
change between dev and stable.

The staging workflow observes the existing image watchers; it cannot deploy or
restart the applications. On both hosts, install `bin/staging-acceptance-host.sh`
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
plugin results, host OOM kills, and real rendered snapshot pages. Logs, result
inventories and screenshots are retained as Actions artifacts. Failures remain
failures; do not publish a success deployment record to bypass them. No code
mounts are allowed. Both matrix jobs must pass before their records authorize a
stable upload. Queued capture progress is polled; failed tests are not retried.
