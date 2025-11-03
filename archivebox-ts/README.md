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
│   ├── downloads        # Catches file downloads
│   ├── images           # Catches all images
│   ├── infiniscroll     # Scrolls to load lazy content
│   ├── favicon          # Downloads favicon
│   ├── title            # Extracts title (reuses Chrome tab)
│   ├── headers          # Extracts headers (reuses Chrome tab)
│   ├── screenshot       # Takes screenshot (reuses Chrome tab)
│   └── ...              # And more extractors
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

1. **2captcha** - Downloads and configures Chrome extensions (2captcha, singlefile, uBlock, etc.)
2. **puppeteer** - Launches Chrome with extensions, writes CDP URL to `.env`
3. **downloads** - Catches file downloads (reloads page with listeners)
4. **images** - Catches all images (reloads page with listeners)
5. **infiniscroll** - Scrolls page to load lazy content
6. **favicon** - Downloads favicon (can work independently)
7. **title** - Extracts title using existing Chrome tab
8. **headers** - Extracts headers using existing Chrome tab
9. **screenshot** - Takes screenshot using existing Chrome tab
10. **pdf** - Generates PDF using existing Chrome tab
11. **dom** - Extracts DOM HTML using existing Chrome tab
12. **htmltotext** - Extracts plain text using existing Chrome tab
13. **readability** - Extracts article content using existing Chrome tab
14. **singlefile** - Creates single-file archive using browser extension
15. **wget** - Downloads with wget (independent)
16. **git** - Clones git repository (independent)
17. **media** - Downloads media with yt-dlp (independent)
18. **archive_org** - Submits to Internet Archive (independent)

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

### 2captcha
- **Language**: Node.js
- **Dependencies**: unzip-crx-3
- **Output**: `./extensions/` directory with unpacked Chrome extensions
- **Config**:
  - `API_KEY_2CAPTCHA` - 2Captcha API key for CAPTCHA solving (optional)
  - `EXTENSIONS_ENABLED` - Comma-separated list of extensions to enable (default: all)
- **Purpose**: Downloads and configures Chrome extensions before browser launch
- **Extensions included**:
  - `2captcha` - Automatic CAPTCHA solving
  - `singlefile` - Single-file HTML archiving
  - `ublock` - Ad blocking
  - `istilldontcareaboutcookies` - Cookie consent blocker
- **Note**: Must run BEFORE puppeteer extractor

### puppeteer
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer (includes Chrome)
- **Output**: Writes to `.env` file
- **Config**:
  - `PUPPETEER_TIMEOUT` - Timeout in milliseconds (default: 30000)
  - `CHROME_USER_DATA_DIR` - Chrome user data directory (default: ~/.chrome-archivebox)
  - `CHROME_EXTENSIONS_PATHS` - From .env (set by 2captcha extractor)
  - `CHROME_EXTENSIONS_IDS` - From .env (set by 2captcha extractor)
- **Purpose**: Launches Chrome with extensions and makes CDP URL available to other extractors
- **Note**: Runs in headed mode if extensions are loaded (extensions require visible browser)

### downloads
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome (from puppeteer extractor)
- **Output**: Files downloaded by the page to current directory
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `DOWNLOADS_TIMEOUT` - Maximum time to wait for downloads in ms (default: 30000)
- **Purpose**: Captures file downloads triggered by page load using CDP download handlers

### images
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome (from puppeteer extractor)
- **Output**: `images/` directory with all images from the page
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `IMAGES_TIMEOUT` - Maximum time to wait for page load in ms (default: 30000)
- **Purpose**: Captures all image HTTP responses based on MIME type

### infiniscroll
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome (from puppeteer extractor)
- **Output**: No direct output (modifies page state for other extractors)
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `INFINISCROLL_SCROLLS` - Number of times to scroll down (default: 10)
  - `INFINISCROLL_WAIT` - Time to wait between scrolls in ms (default: 1000)
  - `INFINISCROLL_DISTANCE` - Scroll distance in pixels (default: viewport height)
- **Purpose**: Scrolls page to trigger lazy-loaded content, then scrolls back to top

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

### pdf
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome (from puppeteer extractor)
- **Output**: `output.pdf`
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `PDF_TIMEOUT` - Timeout in milliseconds (default: 30000)
  - `PDF_FORMAT` - Page format: Letter, A4, etc. (default: A4)

### dom
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome (from puppeteer extractor)
- **Output**: `output.html`
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `DOM_TIMEOUT` - Timeout in milliseconds (default: 10000)

### htmltotext
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome (from puppeteer extractor)
- **Output**: `output.txt`
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `HTMLTOTEXT_TIMEOUT` - Timeout in milliseconds (default: 10000)

### readability
- **Language**: Node.js with Mozilla Readability
- **Dependencies**: puppeteer-core, jsdom, @mozilla/readability, Chrome (from puppeteer extractor)
- **Output**: `readability.html` and `readability.json`
- **Requires**: puppeteer extractor must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `READABILITY_TIMEOUT` - Timeout in milliseconds (default: 10000)

### singlefile
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, SingleFile browser extension (from 2captcha extractor)
- **Output**: `singlefile.html`
- **Requires**: 2captcha and puppeteer extractors must run first
- **Config**:
  - `CHROME_CDP_URL` - From .env (set by puppeteer extractor)
  - `CHROME_PAGE_TARGET_ID` - From .env (set by puppeteer extractor)
  - `CHROME_USER_DATA_DIR` - For finding downloads directory
  - `SINGLEFILE_TIMEOUT` - Timeout in seconds (default: 60)
- **Purpose**: Creates single-file HTML archive using the SingleFile browser extension
- **Note**: Triggers extension via Ctrl+Shift+Y keyboard shortcut

### wget
- **Language**: Bash
- **Dependencies**: wget (auto-installed)
- **Output**: `warc/archive.warc.gz` and downloaded files
- **Config**:
  - `WGET_TIMEOUT` - Timeout in seconds (default: 60)
  - `WGET_USER_AGENT` - User agent string
  - `WGET_ARGS` - Additional wget arguments

### git
- **Language**: Bash
- **Dependencies**: git (auto-installed)
- **Output**: `git/` directory with cloned repository
- **Config**:
  - `GIT_TIMEOUT` - Timeout in seconds (default: 300)
  - `GIT_DEPTH` - Clone depth (default: full clone)
- **Note**: Only runs if URL appears to be a git repository

### media
- **Language**: Bash
- **Dependencies**: yt-dlp (auto-installed)
- **Output**: `media/` directory with downloaded media files
- **Config**:
  - `MEDIA_TIMEOUT` - Timeout in seconds (default: 3600)
  - `MEDIA_MAX_SIZE` - Max file size (default: 750m)
  - `MEDIA_FORMAT` - Format selection (default: best)

### archive_org
- **Language**: Bash
- **Dependencies**: curl (auto-installed)
- **Output**: `archive_org.txt` with archived URL
- **Config**:
  - `ARCHIVE_ORG_TIMEOUT` - Timeout in seconds (default: 60)

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
