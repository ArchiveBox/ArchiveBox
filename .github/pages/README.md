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
6. Serialize production restore/build/deploy under one concurrency group and
   check out the latest default-branch revision when each build starts. Keep the
   built revision in provenance; later release-bot commits must not block deploys.
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

`base/` contains identical independent copies across the seven product sites.
Common Python scripts share the same behavior; repository formatters may change
line wrapping without changing their syntax trees. The base owns the shared logo, Apps menu/icons, footer directory, navigation
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

## Branding and future translations

`base/chrome.css` owns the shared system font stacks, plum accent and CTA shape,
including the existing `.button` and `.ab-btn` classes. Product styles own their
layouts, feature sections and platform-specific button states. Shared system
fonts need no external font downloads. `site.py` emits the same complete SEO/OG/
Twitter tags everywhere while retaining each native template's title, description,
canonical URL, locale and social artwork; edit those values with that page's copy.

For translations, keep complete separate HTML files under `es/`, `fr/` and `zh/`,
and list their output paths in `site.json` alongside the English pages. Share CSS,
JS, social artwork and the English screenshot gallery. Translate each page's title
and description, set its own canonical and `lang` (`zh` for Chinese), and add
reciprocal `hreflang` links only for translations that actually exist. The renderer
preserves these tags and computes shared asset paths for nested pages. Localized
header/footer copy and the small language selector can be added with those pages;
there is no language redirect, placeholder translation or translation runtime now.

## Screenshot strips

`marquee.py` and `base/marquee.css` / `base/marquee.js` are also identical copies.
Product homepages choose their placement with an `ARCHIVEBOX:MARQUEE` comment.
The renderer takes real images, captions, dimensions and links from the generated
`screenshots/index.html`; there is no second screenshot list or browser fetch.
Desktop/tablet/mobile galleries contribute their desktop views. Apple uses
`MARQUEE-CLIENT` and `MARQUEE-SERVER` slots to keep its two products separate.
Catalog sites without a slot do not load the strip assets.

The strip scrolls once, pauses on hover, focus or manual interaction, and has an
explicit Play/Pause button. Reduced-motion users start paused. Without JavaScript,
normal image links and horizontal scrolling remain available. Screenshot capture
manifests and provenance are never rewritten by this presentation step.

Standalone one- or two-image illustrations remain in their authored source.
Gallery strips with three or more images use the latest restored captures.

## Keeping the common layout in sync

The comments in `base/header.html`, `base/footer-start.html`,
`base/footer-end.html`, `base/chrome.css`, and `base/chrome.js` list the peer
repositories. Update those committed copies together when shared branding,
Apps links, keyboard behavior, or footer resources change. Preserve each site's
local navigation and content. The former monorepo `site-chrome` generator is
retired; builds must use only this repository's files.
