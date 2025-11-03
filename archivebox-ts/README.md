# ArchiveBox TypeScript

A TypeScript-based version of ArchiveBox with a simplified, modular architecture.

## Overview

This is a reimplementation of ArchiveBox using TypeScript with a focus on simplicity and modularity. The key architectural changes are:

1. **Standalone Extractors**: Each extractor is a standalone executable (bash, Node.js, or Python with shebang) that can run independently
2. **Serial Execution with Shared State**: Extractors run in a predefined order and can pass environment variables via a `.env` file
3. **Auto-Installing Dependencies**: Extractors automatically install their own dependencies when first run
4. **Simple Interface**: Extractors receive URL as `$1` CLI argument and output files to current working directory
5. **Environment-Based Config**: All configuration passed via environment variables, no CLI flags
6. **SQLite Database**: Uses SQLite with schema matching the original ArchiveBox

## Key Innovation: Shared Browser Instance

The `puppeteer` extractor launches Chrome once and writes the CDP URL to `.env`. All subsequent browser-based extractors (title, headers, screenshot, dom) reuse the same browser tab, making extraction much faster and more efficient.

## Directory Structure

```
archivebox-ts/
├── src/
│   ├── cli.ts           # Main CLI entry point
│   ├── db.ts            # SQLite database operations
│   ├── models.ts        # TypeScript interfaces
│   └── extractors.ts    # Extractor orchestration (serial execution)
├── extractors/          # Standalone extractor executables (predefined order)
│   ├── puppeteer        # Launches Chrome, writes CDP URL to .env
│   ├── favicon          # Downloads favicon
│   ├── title            # Extracts title (reuses Chrome tab)
│   ├── headers          # Extracts headers (reuses Chrome tab)
│   ├── screenshot       # Takes screenshot (reuses Chrome tab)
│   └── wget             # Full page download
├── data/                # Created on init
│   ├── index.sqlite3    # SQLite database
│   └── archive/         # Archived snapshots
│       └── <timestamp>_<domain>/
│           ├── .env     # Extractor environment variables
│           ├── favicon.ico
│           ├── title.txt
│           ├── screenshot.png
│           └── ...
├── package.json
├── tsconfig.json
└── README.md
```

## Installation

### Prerequisites

- Node.js 18+ and npm
- Chrome or Chromium browser (installed locally)
- For specific extractors:
  - `wget` extractor: wget
  - `puppeteer`, `screenshot`, `title`, `headers` extractors: Chrome/Chromium

### Setup

```bash
cd archivebox-ts

# Install dependencies
npm install

# Build TypeScript
npm run build

# Initialize ArchiveBox
node dist/cli.js init
```

## Usage

### Initialize

Create the data directory and database:

```bash
node dist/cli.js init
```

### Add a URL

Archive a URL with all available extractors (runs in predefined order):

```bash
node dist/cli.js add https://example.com
```

Archive with specific extractors:

```bash
node dist/cli.js add https://example.com --extractors puppeteer,title,screenshot
```

Add with custom title:

```bash
node dist/cli.js add https://example.com --title "Example Domain"
```

### List Snapshots

List all archived snapshots:

```bash
node dist/cli.js list
```

With pagination:

```bash
node dist/cli.js list --limit 10 --offset 20
```

### Check Status

View detailed status of a snapshot:

```bash
node dist/cli.js status <snapshot-id>
```

### List Extractors

See all available extractors in execution order:

```bash
node dist/cli.js extractors
```

## Extractor Execution Order

Extractors run serially in this predefined order (defined in `src/extractors.ts`):

1. **puppeteer** - Launches Chrome, writes CDP URL to `.env`
2. **favicon** - Downloads favicon
3. **title** - Extracts title using existing Chrome tab
4. **headers** - Extracts headers using existing Chrome tab
5. **screenshot** - Takes screenshot using existing Chrome tab
6. **dom** - Extracts DOM using existing Chrome tab
7. **wget** - Downloads with wget
8. **singlefile** - Single file archive
9. **readability** - Readable content extraction
10. **media** - Media downloads
11. **git** - Git clone
12. **archive_org** - Submit to archive.org

Only extractors that are both:
- Requested (via `--extractors` or default: all)
- Available (executable file exists in `extractors/`)

will actually run.

## Environment Variable Sharing via .env

Each snapshot directory contains a `.env` file that extractors can:
- **Read**: Load environment variables set by previous extractors
- **Write**: Append new environment variables for subsequent extractors

Example `.env` file after puppeteer extractor:

```bash
# ArchiveBox Snapshot Environment
# Created: 2025-11-03T20:00:00.000Z
# URL: https://example.com

# Chrome browser connection info (written by puppeteer extractor)
CHROME_CDP_URL="ws://127.0.0.1:12345/devtools/browser/..."
CHROME_PAGE_TARGET_ID="ABC123..."
CHROME_USER_DATA_DIR="/home/user/.chrome-archivebox"
```

Subsequent extractors automatically receive these variables.

## Database Schema

The SQLite database uses a schema compatible with ArchiveBox:

### Snapshots Table

Represents a single URL being archived.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT (UUID) | Primary key |
| abid | TEXT | ArchiveBox ID (snp_...) |
| url | TEXT | URL being archived (unique) |
| timestamp | TEXT | Unix timestamp string |
| title | TEXT | Page title |
| created_at | TEXT | ISO datetime |
| bookmarked_at | TEXT | ISO datetime |
| downloaded_at | TEXT | ISO datetime when complete |
| modified_at | TEXT | ISO datetime |
| status | TEXT | queued, started, sealed |
| retry_at | TEXT | ISO datetime for retry |
| config | TEXT (JSON) | Configuration |
| notes | TEXT | Extra notes |
| output_dir | TEXT | Path to output directory |

### Archive Results Table

Represents the result of running one extractor on one snapshot.

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT (UUID) | Primary key |
| abid | TEXT | ArchiveBox ID (res_...) |
| snapshot_id | TEXT | Foreign key to snapshot |
| extractor | TEXT | Extractor name |
| status | TEXT | queued, started, succeeded, failed, skipped, backoff |
| created_at | TEXT | ISO datetime |
| modified_at | TEXT | ISO datetime |
| start_ts | TEXT | ISO datetime when started |
| end_ts | TEXT | ISO datetime when finished |
| cmd | TEXT (JSON) | Command executed |
| pwd | TEXT | Working directory |
| cmd_version | TEXT | Binary version |
| output | TEXT | Output file path or result |
| retry_at | TEXT | ISO datetime for retry |
| config | TEXT (JSON) | Configuration |
| notes | TEXT | Extra notes |

## Available Extractors

### puppeteer
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer (includes Chrome)
- **Output**: Writes to `.env` file
- **Config**:
  - `PUPPETEER_TIMEOUT` - Timeout in milliseconds (default: 30000)
  - `CHROME_USER_DATA_DIR` - Chrome user data directory (default: ~/.chrome-archivebox)
- **Purpose**: Launches Chrome and makes CDP URL available to other extractors

### favicon
- **Language**: Bash
- **Dependencies**: curl (auto-installed)
- **Output**: `favicon.ico` or `favicon.png`
- **Config**:
  - `FAVICON_TIMEOUT` - Timeout in seconds (default: 10)

### title
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome (from puppeteer extractor)
- **Output**: `title.txt`
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `TITLE_TIMEOUT` - Timeout in milliseconds (default: 10000)

### headers
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome (from puppeteer extractor)
- **Output**: `headers.json`
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `HEADERS_TIMEOUT` - Timeout in milliseconds (default: 10000)

### screenshot
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome (from puppeteer extractor)
- **Output**: `screenshot.png`
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `SCREENSHOT_TIMEOUT` - Timeout in milliseconds (default: 30000)
  - `SCREENSHOT_WIDTH` - Viewport width (default: 1920)
  - `SCREENSHOT_HEIGHT` - Viewport height (default: 1080)
  - `SCREENSHOT_WAIT` - Wait time before screenshot in ms (default: 1000)

### wget
- **Language**: Bash
- **Dependencies**: wget (auto-installed)
- **Output**: `warc/archive.warc.gz` and downloaded files
- **Config**:
  - `WGET_TIMEOUT` - Timeout in seconds (default: 60)
  - `WGET_USER_AGENT` - User agent string
  - `WGET_ARGS` - Additional wget arguments

## Creating Custom Extractors

Extractors are standalone executable files in the `extractors/` directory.

### Extractor Contract

1. **Executable**: File must have execute permissions (`chmod +x`)
2. **Shebang**: Must start with shebang (e.g., `#!/bin/bash`, `#!/usr/bin/env node`)
3. **First Argument**: Receives URL as `$1` (bash) or `process.argv[2]` (Node.js) or `sys.argv[1]` (Python)
4. **Working Directory**: Run in the output directory, write files there
5. **Environment Config**: Read all config from environment variables (including from `.env`)
6. **Exit Code**: Return 0 for success, non-zero for failure
7. **Output**: Print the main output file path to stdout
8. **Logging**: Print progress/errors to stderr
9. **State Sharing**: Can append to `.env` file to pass variables to later extractors

### Adding to Execution Order

To add your extractor to the predefined order, edit `src/extractors.ts`:

```typescript
export const EXTRACTOR_ORDER: string[] = [
  'puppeteer',
  'favicon',
  'title',
  // ... other extractors ...
  'your-new-extractor',  // Add here
];
```

### Example: Extractor that Uses .env

```bash
#!/bin/bash
set -e

URL="$1"

# Read from .env (automatically loaded by ExtractorManager)
echo "Chrome CDP URL: $CHROME_CDP_URL" >&2

# Do your extraction work
echo "Processing $URL..." >&2

# Write output
echo "result" > output.txt

# Append to .env for next extractor
echo "MY_EXTRACTOR_RESULT=\"success\"" >> .env

echo "output.txt"
exit 0
```

## Development

### Build

```bash
npm run build
```

### Watch Mode

```bash
npm run dev
```

### Project Structure

- `src/models.ts` - TypeScript interfaces matching the database schema
- `src/db.ts` - Database layer with SQLite operations
- `src/extractors.ts` - Extractor discovery and serial orchestration
- `src/cli.ts` - CLI commands and application logic

## Differences from Original ArchiveBox

### Simplified

1. **No Plugin System** → Executable files
2. **Simpler Config** → Environment variables + `.env` file
3. **No Web UI** → CLI only (for now)
4. **No Background Workers** → Direct execution
5. **No Multi-user** → Single-user mode

### Architecture Improvements

1. **Serial Execution** - Predictable order, state sharing via `.env`
2. **Shared Browser** - One Chrome instance for all browser-based extractors
3. **Language Agnostic** - Write extractors in any language
4. **Easy to Test** - Each extractor can be tested standalone
5. **Simpler Dependencies** - Each extractor manages its own

## Future Enhancements

- [ ] Background job queue for processing
- [ ] Web UI for browsing archives
- [ ] Search functionality
- [ ] More extractors (dom, singlefile, readability, etc.)
- [ ] Import/export functionality
- [ ] Schedule automatic archiving
- [ ] Browser extension integration

## License

MIT

## Credits

Based on [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox) by Nick Sweeting and contributors.
