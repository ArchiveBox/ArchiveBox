## Changes since v0.9.50

- 🗂️ Refreshed archive and snapshot pages, with saved outputs grouped into stacks. Cards show the same content whether the stack is open or closed.
- 📚 Extract text from downloaded research papers and documents with LiteParse and OpenDataLoader. Preview the original files alongside the extracted text.
- 🖼️ Improved PDF, SEO, and timestamp-proof previews. Embedded-media cards show each captured file once instead of repeating duplicate downloads.
- 📱 Improved Add URL and snapshot layouts on smaller screens, including the embedded views in our Apple apps.
- ⚙️ More reliable crawling: reuse the browser across pages in a crawl, avoid busy-looping on work already in progress, and keep server reloads from interrupting foreground captures.
- 🌐 Fixed favicon display, including SVG icons, and navigation between saved snapshots.
- 🗃️ Fixed older snapshots failing to open after migration, including archives created in non-UTC time zones.
- 🔗 Fixed saved-output links and previews across server security modes, including encoded filenames and older static archives. Cards keep their titles and previews when an older archive has an incomplete file manifest.
