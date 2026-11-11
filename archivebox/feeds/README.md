# RSS sources and saved lists

The Feeds page creates scheduled RSS subscriptions using the existing RSS importer.
Provide a feed URL, or a route and instance URL for RSSHub-supported sites. Preview
and start imports using the ordinary Importers controls. Websites still need a feed
or an available RSSHub route; this does not promise arbitrary website conversion.

“RSS for this list” saves the current admin filters and search as a revocable feed
link. The feed re-evaluates those filters on each request and returns up to 500
snapshots. Feeds contain public snapshots by default. Including private or unlisted
captures requires explicit opt-in; anyone holding that link can read those entries.
Disable a link using Revoke. An inactive or non-superuser creator invalidates it.

The screenshot collector creates a real Hacker News subscription and exports the
captured Hacker News folder through normal browser forms. Gallery captures are
registered for all supported viewports by `gallery.js`.
