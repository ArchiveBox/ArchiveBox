## Changes since v0.9.70

- ⚡ **Faster browsing in large archives.** Public snapshot pages render without waiting to count the whole collection, and reuse saved metadata instead of repeatedly querying each item. Totals may appear on a later reload while captures are running.
- 📊 **Lighter live progress.** Progress checks use read-only, indexed queries instead of performing filesystem and lifecycle work on each poll. Waiting for a tool's first result no longer burns a CPU core.
- 🔄 **More reliable stops, restarts and runner takeover.** Fix shutdown hangs while reaping child processes and honor interruptions during resumed startup. A displaced runner leaves captures available for its replacement to resume; an explicit user abort still seals that capture attempt.
- 🔗 **Preserve apostrophes in imported URLs.** Shared parsing now respects the surrounding text, Markdown, CSV or JSON format instead of cutting URLs off at an embedded quote.
- 🌐 **More dependable browser captures.** ArchiveWeb.page's helper stays in the background, and capture readiness checks continue to work when that tab is hidden. Browser-extension upload recovery reuses the existing hook index.
- 🛠️ **More reliable Python and Node tools.** Fix Python hooks launched through shared binary locations without losing their virtual environment, and stop discarding valid managed tool installations when an unrelated executable is rejected.
- 📱 **Cleaner snapshot cards on narrow screens.** Long tags and labels fit more gracefully in the public list and admin grid.
- 🚀 **Faster delivery of fixes.** Reduce repeated CI and screenshot work, keep available runners busy, and publish the exact packages and images that passed testing. Release checks also verify that captured pages actually render on staging.

Upgrades also repair migrated process links and register the CLI's machine explicitly during startup. The pinned downloader, plugins and runtime libraries include these fixes; no manual dependency updates are needed.
