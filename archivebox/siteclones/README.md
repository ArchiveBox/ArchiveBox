# Clone a site

Superusers open **Clone a site** at `/admin/site-clones/`, choose an HTTP(S)
starting URL and set page, time, concurrency and depth budgets. The form creates
an ordinary Crawl, processed by the existing ArchiveBox worker. It does not start
a second crawler or scheduler.

Leave **Repeat** blank for a one-time clone, or enter an alias such as `daily`
or a cron expression. Recurring clones use the existing `CrawlSchedule` runner,
preserving explicit domain filters, page/time/concurrency budgets, plugins,
visibility, tags and Persona. The detail page shows the next run, recent runs,
and the normal schedule management page. Pausing a crawl pauses that run;
disable its schedule separately to prevent future runs.

The default boundary is the exact hostname, with optional subdomains. An explicit
port stays scoped to that port. Path exclusions apply to that path and its
children. The configured URL denylist remains in force. Captures use the selected
Persona, visibility, tags and capture plugins. Leave the plugin selection empty
to use configured defaults; a custom selection needs link discovery enabled.

The progress page links to saved snapshots, normal Crawl settings and logs. Pause
and resume retain the same queue and captured files. Limits still apply after
resume, so increase an exhausted budget in Crawl settings before continuing.
Depth is currently limited to four hops by the shared crawl engine. A finished
queue only means the selected scope was processed, not that every page on a site
was discovered. External links are intentionally outside the site clone; import
them separately when desired.

`gallery.js` submits a real bounded Hacker News clone through the logged-in
browser and returns its progress URL. The screenshot collector runs the ordinary
worker before photographing this page, so the gallery contains actual captures.

Verification:

```sh
uv run pytest archivebox/tests/test_siteclones.py -x
```
