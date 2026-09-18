# UI Screenshots

[Open the ArchiveBox screenshot gallery](https://archivebox.io/screenshots/).

The gallery covers public and authenticated views at desktop, tablet, and mobile
sizes. Each view links to its implementation, and the gallery records the version,
commit, image hashes, and capture count. API endpoints, health checks, and error
routes are excluded.

The [Pages workflow](https://github.com/ArchiveBox/ArchiveBox/blob/dev/.github/workflows/deploy-publicsite.yml)
regenerates the gallery from its checkout before deployment. Images and gallery
markup are build outputs, so this documentation does not keep another generated copy.

To capture a local gallery, run `bin/collect_ui_screenshots.sh` from the repository.
It drives real browser sessions and CLI captures. The output is
`publicsite/screenshots/index.html`; set `UI_SCREENSHOT_PUBLIC_OUTPUT_DIR` to choose
another destination and `UI_SCREENSHOT_DATA_DIR` to select the collection.
