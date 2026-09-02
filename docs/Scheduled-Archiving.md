# Scheduled Archiving

ArchiveBox now stores schedules in the database and lets the orchestrator materialize them into queued `Crawl` records at the right time. You no longer need host cron, user crontabs, or a separate `archivebox_scheduler` container when `archivebox server` is running.

## How It Works

1. `archivebox schedule ...` creates a `CrawlSchedule` record plus a sealed template `Crawl`.
2. The long-running global orchestrator inside `archivebox server` watches enabled schedules.
3. When a schedule becomes due, the orchestrator creates a new queued `Crawl`.
4. That queued crawl is processed the same way as UI/API-submitted work.

One-shot foreground flows such as `archivebox add ...` continue to process only the crawl they were asked to run. They do not also sweep and execute unrelated scheduled crawls.

## CLI Usage

```bash
cd ~/archivebox/data

archivebox schedule --every=daily --depth=1 https://example.com/feed.xml
archivebox schedule --every='0 */6 * * *' https://example.com/feed.xml
archivebox schedule --show
archivebox schedule --clear
archivebox schedule --run-all
archivebox schedule --foreground
```

Accepted schedule formats:

- Aliases: `minute`, `hour`, `day`, `week`, `month`, `year`, `daily`, `weekly`, `monthly`, `yearly`
- Cron expressions: e.g. `0 */6 * * *`

`archivebox schedule --run-all` dispatches every enabled schedule immediately: crawl schedules are enqueued, while maintenance schedules run directly.

`archivebox schedule --foreground` runs the global orchestrator in the foreground, which is useful outside `archivebox server` if you want a dedicated long-running scheduler/worker process without the web UI.

Running `archivebox schedule --every=day` with no `import_path` creates a recurring maintenance schedule. The scheduler dispatches its bounded database/filesystem maintenance directly instead of creating a synthetic Crawl or Snapshot.

## Docker Compose

With the new orchestrator flow, you only need the main `archivebox` service:

```yaml
services:
  archivebox:
    image: archivebox/archivebox:dev
    command: server --init 0.0.0.0:8000
    volumes:
      - ./data:/data
```

Create schedules with:

```bash
docker compose run --rm archivebox schedule --every=weekly --depth=1 https://example.com/feed.xml
docker compose run --rm archivebox schedule --show
```

If the main `archivebox server` container is already running, its orchestrator will pick up future scheduled runs automatically. There is no scheduler sidecar to restart.

## Examples

Archive a Twitter mirror once a week:

```bash
archivebox schedule --every=weekly --depth=1 'https://nitter.net/ArchiveBoxApp'
```

Archive a subreddit and linked discussions once a week:

```bash
archivebox config --set URL_ALLOWLIST='^http(s)?:\/\/(.+)?teddit\.net\/?.*$'
archivebox schedule --every=weekly --depth=1 'https://teddit.net/r/DataHoarder/'
```

Archive Hacker News every day:

```bash
archivebox config --set URL_DENYLIST='^http(s)?:\/\/(.+\.)?(youtube\.com)|(amazon\.com)\/.*$'
archivebox schedule --every=daily --depth=1 'https://news.ycombinator.com'
```

Queue a daily maintenance update:

```bash
archivebox schedule --every=day
```
