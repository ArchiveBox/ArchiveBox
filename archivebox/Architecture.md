# ArchiveBox UI

## Page: Getting Started

### What do you want to capture?

- Save some URLs now -> [Add page]
    - Paste some URLs to archive now
    - Upload a file containing URLs (bookmarks.html export, RSS.xml feed, markdown file, word doc, PDF, etc.)
    - Pull in URLs to archive from a remote location (e.g. RSS feed URL, remote TXT file, JSON file, etc.)

- Import URLs from a browser -> [Import page]
    - Desktop: Get the ArchiveBox Chrome/Firefox extension
    - Mobile: Get the ArchiveBox iOS App / Android App
    - Upload a bookmarks.html export file
    - Upload a browser_history.sqlite3 export file

- Import URLs from a 3rd party bookmarking service -> [Sync page]
    - Pocket
    - Pinboard
    - Instapaper
    - Wallabag
    - Zapier, N8N, IFTTT, etc.
    - Upload a bookmarks.html export, bookmarks.json, RSS, etc. file

- Archive URLs on a schedule -> [Schedule page]

- Archive an entire website -> [Crawl page]
    - What starting URL/domain?
    - How deep?
    - Follow links to external domains?
    - Follow links to parent URLs?
    - Maximum number of pages to save?
    - Maximum number of requests/minute?

- Crawl for URLs with a search engine and save automatically
    - 
- Some URLs on a schedule
- Save an entire website (e.g. `https://example.com`)
- Save results matching a search query (e.g. "site:example.com")
- Save a social media feed (e.g. `https://x.com/user/1234567890`)

--------------------------------------------------------------------------------

### Crawls App

- Archive an entire website -> [Crawl page]
    - What are the seed URLs?
    - How many hops to follow?
    - Follow links to external domains?
    - Follow links to parent URLs?
    - Maximum number of pages to save?
    - Maximum number of requests/minute?


--------------------------------------------------------------------------------

### Scheduler App


- Archive URLs on a schedule -> [Schedule page]
    - What URL(s)?
    - How often?
    - Do you want to discard old snapshots after x amount of time?
    - Any filter rules?
    - Want to be notified when changes are detected -> redirect[Alerts app/create new alert(crawl=self)]


* Choose Schedule check for new URLs: Schedule.objects.get(pk=xyz)
    - 1 minute
    - 5 minutes
    - 1 hour
    - 1 day

    * Choose Destination Crawl to archive URLs using : Crawl.objects.get(pk=xyz)
        - Tags
        - Persona
        - Created By ID
        - Config
        - Filters
            - URL patterns to include
            - URL patterns to exclude
            - ONLY_NEW= Ignore URLs if already saved once / save URL each time it appears / only save is last save > x time ago


--------------------------------------------------------------------------------

### Sources App (For managing sources that ArchiveBox pulls URLs in from)

- Add a new source to pull URLs in from (WIZARD)
    - Choose URI:
        - [x] Web UI
        - [x] CLI
        - Local filesystem path (directory to monitor for new files containing URLs)
        - Remote URL (RSS/JSON/XML feed)
        - Chrome browser profile sync (login using gmail to pull bookmarks/history)
        - Pocket, Pinboard, Instapaper, Wallabag, etc.
        - Zapier, N8N, IFTTT, etc.
        - Local server filesystem path (directory to monitor for new files containing URLs)
        - Google drive (directory to monitor for new files containing URLs)
        - Remote server FTP/SFTP/SCP path (directory to monitor for new files containing URLs)
        - AWS/S3/B2/GCP bucket (directory to monitor for new files containing URLs)
        - XBrowserSync (login to pull bookmarks)
    - Choose extractor
        - auto
        - RSS
        - Pocket
        - etc.
    - Specify extra Config, e.g.
        - credentials
        - extractor tuning options (e.g. verify_ssl, cookies, etc.)

- Provide credentials for the source
    - API Key
    - Username / Password
    - OAuth

--------------------------------------------------------------------------------

### Alerts App

- Create a new alert, choose condition
    - Get notified when a site goes down (<x% success ratio for Snapshots)
    - Get notified when a site changes visually more than x% (screenshot diff)
    - Get notified when a site's text content changes more than x% (text diff)
    - Get notified when a keyword appears
    - Get notified when a keyword dissapears
    - When an AI prompt returns some result

- Choose alert threshold:
    - any condition is met
    - all conditions are met
    - condition is met for x% of URLs
    - condition is met for x% of time

- Choose how to notify: (List[AlertDestination])
    - maximum alert frequency
    - destination type: email / Slack / Webhook / Google Sheet / logfile
    - destination info:
        - email address(es)
        - Slack channel
        - Webhook URL

- Choose scope:
    - Choose ArchiveResult scope (extractors): (a query that returns ArchiveResult.objects QuerySet)
        - All extractors
        - Only screenshots
        - Only readability / mercury text
        - Only video
        - Only html
        - Only headers

    - Choose Snapshot scope (URL): (a query that returns Snapshot.objects QuerySet)
        - All domains
        - Specific domain
        - All domains in a tag
        - All domains in a tag category
        - All URLs matching a certain regex pattern

    - Choose crawl scope: (a query that returns Crawl.objects QuerySet)
        - All crawls
        - Specific crawls
        - crawls by a certain user
        - crawls using a certain persona


class AlertDestination(models.Model):
    destination_type: [email, slack, webhook, google_sheet, local logfile, b2/s3/gcp bucket, etc.]
    maximum_frequency
    filter_rules
    credentials
    alert_template: JINJA2 json/text template that gets populated with alert contents