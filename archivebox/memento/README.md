# Memento

This Django app adds RFC 7089 response metadata and datetime negotiation to
ArchiveBox's existing views. All implementation is in `views.py`, imported by
the core views. It has no models, migrations, capture hooks, or runtime
dependencies beyond ArchiveBox and Django.

- `/archive/<original-url>` is a TimeGate. `Accept-Datetime` selects the nearest
  completed capture; ties select the earlier capture. Without the header it
  selects the latest capture. Invalid dates return 400; no eligible capture
  returns 404. Lookup preserves the exact original URL, including its query.
- A canonical Snapshot URL with `?format=link` returns an
  `application/link-format` TimeMap. It includes all eligible captures of that
  exact original URL. Anonymous discovery includes public captures only;
  authenticated staff can discover all captures. Existing direct-access
  permissions still govern the canonical page and replay files.
- Completed Snapshot pages and primary saved plugin outputs carry
  `Memento-Datetime` and `original`, `timegate`, and `timemap` links. Logs,
  directory listings, missing files, and application assets are not Mementos.

Eligibility requires existing `downloaded_at` and nonzero `output_size`.
`Memento-Datetime` uses the persisted Snapshot completion time (`downloaded_at`),
not the bookmark/import time or filesystem modification time. This describes
the Snapshot capture, not the individual HTTP timestamps inside WARC/WACZ files.
Legacy captures missing this metadata are excluded; requests never backfill it.
Explicitly overwriting saved files can invalidate their historical identity;
this app does not introduce revision storage or alter extraction behavior.

For example, use `curl -I -H 'Accept-Datetime: Mon, 28 Sep 2026 12:00:00 GMT'
'https://your-archive.example/archive/https://example.com/'`, then follow the
returned `Location` and `Link` headers. GET and HEAD are both supported.
TimeMaps and TimeGate redirects are generated on demand and are not cached.

## WACZ and WARC downloads

Capture `Link` headers and TimeMap bodies also expose saved `.wacz`, `.warc`,
and `.warc.gz` files as `rel="enclosure"` links. Each link has a media `type`
and an `anchor` identifying its canonical capture, so downloads in a TimeMap
remain associated with the right capture. Links use existing file URLs with
`?raw=1`; there are no new endpoints, exports, indexes, or capture steps.

Discovery reads successful ArchiveResults' existing `output_files` metadata;
it does not scan directories or inspect/repackage archive contents. Untracked
files are not advertised, and files removed outside ArchiveBox can leave stale
links. Public TimeMaps exclude private and unlisted captures and their downloads;
direct download requests retain the existing snapshot permission checks.

Downloads support the existing GET, HEAD, and byte-range handling. WACZ uses
`application/wacz`, WARC uses `application/warc`, and compressed WARC uses
`application/gzip`. Gzip downloads omit HTTP `Content-Encoding`: decompressing
them in transit would break consumers that address offsets in the stored file.
Raw containers do not receive `Memento-Datetime`, since a bundle can contain many
resources captured at different times.

This is archive-download discovery alongside RFC 7089, using the standard
[`enclosure` relation](https://www.iana.org/assignments/link-relations/link-relations.xhtml)
and [link context anchors](https://www.rfc-editor.org/rfc/rfc8288.html#section-3.2).
Memento does not define a universal WACZ/WARC download API. For comparison,
[pywb's Warcserver](https://pywb.readthedocs.io/en/latest/manual/warcserver.html)
can return individual WARC records with their own timestamps; this app exposes
the existing whole files, without implementing pywb's record lookup API.
[ReplayWeb.page can load WACZ/WARC URLs](https://replayweb.page/docs/user-guide/loading/),
but a client must discover/use these links explicitly; it is not guaranteed to
recognize this extension automatically. Cross-origin clients still need the
server's existing CORS policy and any required credentials; this app grants no
additional cross-origin access.

## Why this design

[Issue #162](https://github.com/ArchiveBox/ArchiveBox/issues/162) asks for captures
to identify which original URL they represent and when they were archived.
[Memento's introduction](https://mementoweb.org/guide/quick-intro/) explains how
those headers connect a saved representation to its capture history. Clients
discover the TimeGate and TimeMap through `Link` relations, so this integration
can keep the existing routes instead of introducing another API surface.

The TimeGate uses [RFC 7089 pattern 2.1](https://www.rfc-editor.org/rfc/rfc7089.html#section-4.2.1):
a redirect selects an existing canonical capture while preserving ArchiveBox's
replay-origin isolation. The redirect itself must not claim to be archived;
`Memento-Datetime` belongs on the selected representation. `Vary: Accept-Datetime`
advertises the negotiation dimension even though these redirects are not cached.

[Section 4.5.3](https://www.rfc-editor.org/rfc/rfc7089.html#section-4.5.3) defines
invalid-date handling, endpoint selection outside the available date range, and
the latest-capture default. Nearest-in-time selection within that range is our
policy; chronological ordering makes equal-distance choices deterministic.

TimeMaps use the required [link-format serialization](https://www.rfc-editor.org/rfc/rfc7089.html#section-5).
They enumerate all eligible captures of one exact URL rather than applying the
UI's fuzzy search or truncating to a page without continuation links. Public
discovery excludes unlisted captures because knowing the original URL is not
the same as possessing an unlisted capture's direct link. These permission
rules are ArchiveBox policy, not an RFC requirement.

The [stable-identity requirement](https://www.rfc-editor.org/rfc/rfc7089.html#section-4.5.6)
is why response time, bookmark time, and file modification time cannot stand in
for capture time. Reusing persisted completion metadata avoids request-time
writes or new capture stages, but does not enforce immutability against explicit
overwrites. Likewise, a log or application asset does not become an archived
representation of the original page simply because it shares a snapshot folder;
see [resources excluded from negotiation](https://www.rfc-editor.org/rfc/rfc7089.html#section-4.5.8).
