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

## Editing and building

`base/` and `site.py` are identical independent copies across the seven product
sites. The base owns the shared logo, Apps menu/icons, footer directory, navigation
behavior and styles. `site.json` and `nav.html` contain this site's name, routes,
links and CTA. Product content and additional footer resources stay in the native
HTML/Jinja/Liquid templates listed above. The `ARCHIVEBOX:*` comments are build
slots; the renderer fills them with static HTML, never browser-side fetches.

The existing builder calls `site.py render` after generating its content. This
copies `base/chrome.css` and `base/chrome.js` to `site-base/`, assembles the common
HTML, validates local resources and writes the site revision to root `build.json`.
Screenshot manifests are left untouched. No build reads another repository.

Common changes are manual copy/paste edits. Compare `base/` and `site.py` with
another product repository when updating them; do not add a synchronization job,
package dependency or reusable cross-repository workflow. `nav.html`, `site.json`
and the marked workflow build section are intentionally repository-specific.

Build: `uv run --no-project python .github/pages/site.py render _site --source publicsite` after restoring screenshots and refreshing the gallery.

Check the built site with real Chromium (also run by Pages CI):

```sh
uv run --no-config --no-project --with playwright==1.63.0 playwright install chromium
uv run --no-config --no-project --with playwright==1.63.0 python .github/pages/verify.py SITE_OUTPUT --evidence /tmp/site-evidence
```

Use this workflow's `SITE_OUTPUT` directory. The check covers desktop/mobile
layout, keyboard dismissal, no-JavaScript links, local resources and visible
images, and uploads its screenshots as `site-verification` for 14 days.
