# Link health

Superusers open `/admin/link-health/` to review repeated URLs and request an
availability check. Repeated saves are candidates for review: captures may be
intentional historical versions. No scan merges or deletes captures.

Review issue categories, search titles or URLs, and sort by title or check time.
Each row links to the saved capture and original page. **Recheck** queues just
that capture for the existing worker; another active scan must finish first.
Select individual rows or **Select all on this page**, then **Recheck selected**
to queue up to 50 captures together. Other captures retain their previous results.
Duplicate candidates are grouped below the availability results.

Checks issue anonymous streaming HTTP GET requests and close after headers,
without downloading response bodies or using Persona cookies/netrc credentials.
404/410 means not found/gone; 401/403/407/429 is restricted/rate limited; 5xx is a
server error. TLS, connection, redirect and timeout failures stay separate from
broken links. HTTP success does not prove that a page's content is unchanged.

The worker also computes SHA-256 for the largest saved text/HTML/Markdown output
up to 64 MiB in each capture's successful result manifests. Matching files are
shown as content candidates. The UI states this limited scope; it does not imply
all archive files or complete captures are identical. Missing and oversized
files are left unclassified, never hashed only in part.

Choose an interval in days to enable automatic checks while the normal worker
runs, or leave it at zero for manual scans. Only one scan is active at a time.
Results are committed after each URL; interrupted scans retain completed work.
The next manual or scheduled scan starts from the current sealed captures.

CLI equivalents:

```sh
archivebox manage linkhealth --scan --once
archivebox manage linkhealth --once
```

`gallery.js` submits the actual admin form. The gallery collector runs the CLI
above before photographing results from its real Hacker News capture collection.

```sh
uv run pytest archivebox/tests/test_linkhealth.py -x
```
