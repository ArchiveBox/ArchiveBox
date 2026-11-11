# Storage destinations

Superusers use **Storage** at `/admin/storage/` to save rclone destinations for
Google Drive, Amazon S3, S3-compatible services, or a mounted/local directory.
The connection form persists settings without environment variables. Credentials
live in collection-private `storage/<destination-id>/rclone.<revision>.conf` files (0600),
outside captured files. They are never returned in forms or command arguments.
Each job freezes its destination path and configuration revision when queued.
Edits publish a new credential file before updating the destination record, so
concurrent edits cannot redirect an existing job or replace its credentials.
Old revisions remain private for recorded jobs; pre-revision configurations use
`rclone.conf`. A connection check only marks the same current revision verified.

For Google Drive, create a Google web OAuth client, enable the Drive API, and
register the exact callback URL displayed in the form. Save its client ID and
secret, then select **Sign in with Google**. The browser completes Google's
consent flow; rclone refreshes the resulting offline token. Google requires a
valid HTTPS redirect URL for remote hosts. A service-account JSON key and shared
Drive folder are also supported. These are real provider authentication flows;
no success is assumed before the connection check completes.

**Check connection** queues a write/read-back/delete of a unique temporary file.
**Copy sealed snapshots** queues rclone copies of captures sealed at submission
time, preserving their paths below `archive/`. Every copied directory is checked
against the source with `rclone check --one-way --download`. Existing destination
files are never deleted. Cancellation retains already copied files; another copy
checks and continues them. Failure never counts as verified completion.

ArchiveBox continues to capture and replay from its existing local archive.
This is an additional copy destination, not an active archive mount or a full
collection backup: the database, personas and credentials are excluded. Capture
folders contain original saved content, including any private pages, so select a
destination with appropriate access controls.

The normal ArchiveBox worker handles storage jobs. A CLI equivalent is
`archivebox manage storage --once`. **Install rclone** uses abxpkg and the host's
package manager (Homebrew on macOS, apt on Linux); the server user needs permission
to install packages. Existing installations are reused. Raw provider diagnostics are kept
in private `storage/<destination-id>/<run-id>.log` files, never rendered in HTML.

Tests: `uv run pytest archivebox/tests/test_storage_ui.py -x` uses the real
installed rclone executable and local files. Cloud credentials and Google consent
are needed for separate live provider verification.

The screenshot gallery runs the normal storage setup and copy UI against its
real capture collection, and records desktop/tablet/mobile views. The gallery
uses a local rclone destination so it never needs or publishes cloud credentials.
