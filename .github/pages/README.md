# archivebox.io website

This repository owns its complete website. Build and deploy it without checking
out another repository's website, fetching shared snippets, or calling a shared
workflow. Common files are ordinary committed copies; update them deliberately.

## Repository-specific files

- Content: `publicsite/index.html`.
- Site/gallery generation: `bin/generate_ui_screenshot_gallery.py`.
- Application capture: `bin/collect_ui_screenshots.sh`.
- Deployment branch: `dev`.

## Common publication contract

1. Build pull requests without deploying them.
2. Build website pushes immediately, independently of application capture CI.
3. Restore validated screenshots from trusted default-branch capture jobs.
   Keep the original capture revision, timestamp, coverage and image checksums.
4. Retain `site-screenshots` artifacts for 90 days. After expiry, restore the
   published image set. Never replace a complete gallery with an empty one when
   restoration fails. Apple device groups are independently validated artifacts;
   Android's checked-in bootstrap captures retain their local provenance.
5. Render current content and layout around those captures. Site revision and
   capture revision are separate facts; reusing captures must not relabel them.
6. Serialize production restore/build/deploy under one concurrency group.
   Before deployment, confirm the built source is still the default-branch HEAD.
7. Keep platform-specific build, installation, capture, and completeness checks
   in the application's existing capture workflow. Site-only edits do not need
   to rerun those jobs.

## Common presentation contract

The base header, Apps menu and icons, footer, brand styles and navigation behavior
should remain identical copies across the seven product sites. Put this site's
name, navigation, CTA and extra footer resources outside the common base files.
Preserve real links, anchor IDs, no-JavaScript navigation, keyboard operation,
mobile layout, reduced-motion preferences and existing product-specific content.
Screenshots stay in English. Translation content, when added, lives in separate
HTML files; no runtime translation service or cross-repository dependency.
