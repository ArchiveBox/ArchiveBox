# ArchiveBox TypeScript

A TypeScript-based version of ArchiveBox with a simplified, modular architecture.

## Overview

This is a reimplementation of ArchiveBox using TypeScript with a focus on simplicity and modularity. The key architectural changes are:

1. **Standalone Extractors**: Each extractor is a standalone executable (bash, Node.js, or Python with shebang) that can run independently
2. **Auto-Installing Dependencies**: Extractors automatically install their own dependencies when first run
3. **Simple Interface**: Extractors receive URL as `$1` CLI argument and output files to current working directory
4. **Environment-Based Config**: All configuration passed via environment variables, no CLI flags
5. **SQLite Database**: Uses SQLite with schema matching the original ArchiveBox

## Directory Structure

```
archivebox-ts/
├── src/
│   ├── cli.ts           # Main CLI entry point
│   ├── db.ts            # SQLite database operations
│   ├── models.ts        # TypeScript interfaces
│   └── extractors.ts    # Extractor orchestration
├── extractors/          # Standalone extractor executables
│   ├── favicon          # Bash script to download favicon
│   ├── title            # Node.js script to extract title
│   ├── headers          # Bash script to extract HTTP headers
│   ├── wget             # Bash script for full page download
│   └── screenshot       # Python script for screenshots
├── data/                # Created on init
│   ├── index.sqlite3    # SQLite database
│   └── archive/         # Archived snapshots
├── package.json
├── tsconfig.json
└── README.md
```

## Installation

### Prerequisites

- Node.js 18+ and npm
- Chrome or Chromium browser (for screenshot, title, and headers extractors)
- For specific extractors:
  - `wget` extractor: wget
  - `screenshot`, `title`, `headers` extractors: puppeteer-core + Chrome with remote debugging

### Setup

```bash
cd archivebox-ts

# Install dependencies
npm install

# Build TypeScript
npm run build

# Initialize ArchiveBox
node dist/cli.js init

# Start Chrome with remote debugging (required for screenshot, title, headers extractors)
# In a separate terminal:
chrome --remote-debugging-port=9222 --headless
# Or on Linux:
chromium --remote-debugging-port=9222 --headless

# Set the CDP URL environment variable
export CHROME_CDP_URL="http://localhost:9222"
```

## Usage

### Initialize

Create the data directory and database:

```bash
node dist/cli.js init
```

### Add a URL

First, make sure Chrome is running with remote debugging and CHROME_CDP_URL is set:

```bash
# Terminal 1: Start Chrome
chrome --remote-debugging-port=9222 --headless

# Terminal 2: Get the WebSocket URL
curl http://localhost:9222/json/version | jq -r .webSocketDebuggerUrl

# Set the environment variable (use the URL from above)
export CHROME_CDP_URL="ws://localhost:9222/devtools/browser/..."
```

Archive a URL with all available extractors:

```bash
node dist/cli.js add https://example.com
```

Archive with specific extractors (favicon and wget don't need Chrome):

```bash
node dist/cli.js add https://example.com --extractors favicon,wget
```

Archive with Chrome-based extractors:

```bash
node dist/cli.js add https://example.com --extractors title,headers,screenshot
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

See all available extractors:

```bash
node dist/cli.js extractors
```

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

## Creating Custom Extractors

Extractors are standalone executable files in the `extractors/` directory.

### Extractor Contract

1. **Executable**: File must have execute permissions (`chmod +x`)
2. **Shebang**: Must start with shebang (e.g., `#!/bin/bash`, `#!/usr/bin/env node`)
3. **First Argument**: Receives URL as `$1` (bash) or `process.argv[2]` (Node.js) or `sys.argv[1]` (Python)
4. **Working Directory**: Run in the output directory, write files there
5. **Environment Config**: Read all config from environment variables
6. **Exit Code**: Return 0 for success, non-zero for failure
7. **Output**: Print the main output file path to stdout
8. **Logging**: Print progress/errors to stderr
9. **Auto-Install**: Optionally auto-install dependencies on first run

### Example Bash Extractor

```bash
#!/bin/bash
#
# My Custom Extractor
# Description of what it does
#
# Config via environment variables:
#   MY_TIMEOUT - Timeout in seconds (default: 30)
#

set -e

URL="$1"

if [ -z "$URL" ]; then
  echo "Error: URL argument required" >&2
  exit 1
fi

# Auto-install dependencies (optional)
if ! command -v some-tool &> /dev/null; then
  echo "Installing some-tool..." >&2
  sudo apt-get install -y some-tool
fi

# Get config from environment
TIMEOUT="${MY_TIMEOUT:-30}"

echo "Processing $URL..." >&2

# Do the extraction work
some-tool --timeout "$TIMEOUT" "$URL" > output.txt

echo "✓ Done" >&2
echo "output.txt"
exit 0
```

### Example Node.js Extractor

```javascript
#!/usr/bin/env node
//
// My Custom Extractor
// Config via environment variables:
//   MY_TIMEOUT - Timeout in ms
//

const url = process.argv[2];
if (!url) {
  console.error('Error: URL argument required');
  process.exit(1);
}

const timeout = parseInt(process.env.MY_TIMEOUT || '10000', 10);

console.error(`Processing ${url}...`);

// Do extraction work
// Write files to current directory

console.error('✓ Done');
console.log('output.txt');
```

### Example Python Extractor

```python
#!/usr/bin/env python3
#
# My Custom Extractor
# Config via environment variables:
#   MY_TIMEOUT - Timeout in seconds
#

import sys
import os

url = sys.argv[1] if len(sys.argv) > 1 else None
if not url:
    print("Error: URL argument required", file=sys.stderr)
    sys.exit(1)

timeout = int(os.environ.get('MY_TIMEOUT', '30'))

print(f"Processing {url}...", file=sys.stderr)

# Do extraction work
# Write files to current directory

print("✓ Done", file=sys.stderr)
print("output.txt")
```

## Available Extractors

### favicon
- **Language**: Bash
- **Dependencies**: curl (auto-installed)
- **Output**: `favicon.ico` or `favicon.png`
- **Requires Chrome**: No
- **Config**:
  - `FAVICON_TIMEOUT` - Timeout in seconds (default: 10)

### title
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome browser via CDP
- **Output**: `title.txt`
- **Requires Chrome**: Yes (via CHROME_CDP_URL)
- **Config**:
  - `CHROME_CDP_URL` - Chrome DevTools Protocol WebSocket URL (required)
  - `TITLE_TIMEOUT` - Timeout in milliseconds (default: 10000)

### headers
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome browser via CDP
- **Output**: `headers.json`
- **Requires Chrome**: Yes (via CHROME_CDP_URL)
- **Config**:
  - `CHROME_CDP_URL` - Chrome DevTools Protocol WebSocket URL (required)
  - `HEADERS_TIMEOUT` - Timeout in milliseconds (default: 10000)

### wget
- **Language**: Bash
- **Dependencies**: wget (auto-installed)
- **Output**: `warc/archive.warc.gz` and downloaded files
- **Requires Chrome**: No
- **Config**:
  - `WGET_TIMEOUT` - Timeout in seconds (default: 60)
  - `WGET_USER_AGENT` - User agent string
  - `WGET_ARGS` - Additional wget arguments

### screenshot
- **Language**: Node.js + Puppeteer
- **Dependencies**: puppeteer-core, Chrome browser via CDP
- **Output**: `screenshot.png`
- **Requires Chrome**: Yes (via CHROME_CDP_URL)
- **Config**:
  - `CHROME_CDP_URL` - Chrome DevTools Protocol WebSocket URL (required)
  - `SCREENSHOT_TIMEOUT` - Timeout in milliseconds (default: 30000)
  - `SCREENSHOT_WIDTH` - Viewport width (default: 1920)
  - `SCREENSHOT_HEIGHT` - Viewport height (default: 1080)
  - `SCREENSHOT_WAIT` - Wait time before screenshot in ms (default: 1000)

## Setting up Chrome for Remote Debugging

The `screenshot`, `title`, and `headers` extractors require a Chrome browser accessible via the Chrome DevTools Protocol (CDP). This allows multiple extractors to share a single browser instance.

### Start Chrome with Remote Debugging

```bash
# Linux/Mac
chromium --remote-debugging-port=9222 --headless --disable-gpu

# Or with Chrome
chrome --remote-debugging-port=9222 --headless --disable-gpu

# Windows
chrome.exe --remote-debugging-port=9222 --headless --disable-gpu
```

### Get the WebSocket URL

```bash
# Query the Chrome instance for the WebSocket URL
curl http://localhost:9222/json/version

# Example output:
# {
#   "Browser": "Chrome/120.0.0.0",
#   "Protocol-Version": "1.3",
#   "User-Agent": "Mozilla/5.0...",
#   "V8-Version": "12.0.267.8",
#   "WebKit-Version": "537.36",
#   "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/..."
# }
```

### Set the Environment Variable

```bash
# Extract just the WebSocket URL
export CHROME_CDP_URL=$(curl -s http://localhost:9222/json/version | jq -r .webSocketDebuggerUrl)

# Or set it manually
export CHROME_CDP_URL="ws://localhost:9222/devtools/browser/12345678-1234-1234-1234-123456789abc"

# Verify it's set
echo $CHROME_CDP_URL
```

### Docker Setup

For running in Docker, you can use a separate Chrome container:

```bash
# Start Chrome in a container
docker run -d --name chrome \
  -p 9222:9222 \
  browserless/chrome:latest \
  --remote-debugging-port=9222 \
  --remote-debugging-address=0.0.0.0

# Get the CDP URL
export CHROME_CDP_URL="ws://localhost:9222/devtools/browser/$(curl -s http://localhost:9222/json/version | jq -r .webSocketDebuggerUrl | cut -d'/' -f5-)"

# Run archivebox-ts
node dist/cli.js add https://example.com
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
- `src/extractors.ts` - Extractor discovery and orchestration
- `src/cli.ts` - CLI commands and application logic

## Differences from Original ArchiveBox

### Simplified

1. **No Plugin System**: Instead of a complex ABX plugin framework, extractors are simple executable files
2. **Simpler Config**: Only environment variables, no configuration file parsing
3. **No Web UI**: Command-line only (for now)
4. **No Background Workers**: Direct execution (could be added)
5. **No User System**: Single-user mode

### Architecture Improvements

1. **Extractors are Standalone**: Each extractor can be tested independently
2. **Language Agnostic**: Write extractors in any language (bash, Python, Node.js, Go, etc.)
3. **Easy to Extend**: Just drop an executable file in `extractors/` directory
4. **Minimal Dependencies**: Core system only needs Node.js and SQLite

## Future Enhancements

- [ ] Background job queue for processing
- [ ] Web UI for browsing archives
- [ ] Search functionality
- [ ] More extractors (pdf, dom, singlefile, readability, etc.)
- [ ] Import/export functionality
- [ ] Schedule automatic archiving
- [ ] Browser extension integration

## License

MIT

## Credits

Based on [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox) by Nick Sweeting and contributors.
