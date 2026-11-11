# Snapshot folders

The admin snapshot list and grid share a nested folder sidebar. Create or rename
folders in place, select a parent, collapse branches, and filter a folder including
its descendants. Deleting a folder preserves its snapshots as unfiled.

Sidebar counts include descendants, and folder search reveals matching nested
paths. Drag a folder onto another to nest it; drop between rows to reorder, or
onto All snapshots to move it back to the top level. The edit dialog offers a
keyboard-accessible parent selector with full paths. The sidebar collapses on
small screens so the capture list stays in view.

Drag a snapshot into a folder to move it. Drag any checked snapshot to move the
checked selection together; the existing “select all matching” scope is respected.
The folder action also provides a keyboard-accessible bulk move. Moving snapshots
requires the snapshot change permission. Folders organize database metadata without
moving captured files or changing their visibility.

The recurring screenshot collector captures the live Hacker News homepage and
three current front-page stories through the ordinary capture CLI, validates saved
outputs and screenshots, then creates nested folders and drags the checked captures
through the real browser UI. `library_screenshots.py` prepares captures and
`library_gallery.js` exercises organization. No synthetic captures are inserted.
