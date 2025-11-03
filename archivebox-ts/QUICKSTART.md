# ArchiveBox-TS Quick Start Guide

Get up and running with ArchiveBox-TS in 5 minutes!

## Installation

```bash
cd archivebox-ts

# Install dependencies
npm install

# Build TypeScript
npm run build

# Initialize database and data directory
node dist/cli.js init
```

## Basic Usage

### Archive a URL

```bash
# Archive with all available extractors
node dist/cli.js add "https://example.com"

# Archive with specific extractors
node dist/cli.js add "https://github.com" --extractors title,headers,favicon

# Add a custom title
node dist/cli.js add "https://example.com" --title "Example Domain"
```

### List Archives

```bash
# List all snapshots
node dist/cli.js list

# With pagination
node dist/cli.js list --limit 10 --offset 0
```

### Check Status

```bash
# Get the snapshot ID from list command
node dist/cli.js status <snapshot-id>
```

### List Extractors

```bash
# See what extractors are available
node dist/cli.js extractors
```

## Directory Structure After Init

```
archivebox-ts/
├── data/
│   ├── index.sqlite3              # SQLite database
│   └── archive/                   # Archived content
│       └── <timestamp>_<domain>/  # Individual snapshot directories
│           ├── headers.json
│           ├── title.txt
│           ├── favicon.ico
│           └── ...
```

## Environment Variables

Configure extractors using environment variables:

```bash
# Set favicon timeout
export FAVICON_TIMEOUT=30

# Set screenshot dimensions
export SCREENSHOT_WIDTH=1920
export SCREENSHOT_HEIGHT=1080

# Run with custom config
node dist/cli.js add "https://example.com" --extractors screenshot
```

## Example Session

```bash
# Initialize
$ node dist/cli.js init
Initializing ArchiveBox...
Data directory: /path/to/data
Database: /path/to/data/index.sqlite3
Archive directory: /path/to/data/archive
✓ Initialization complete!

# Add a URL
$ node dist/cli.js add "https://example.com"
Adding URL: https://example.com
✓ Created snapshot: 488ef9a8-fcd3-40c7-a209-3ab3b0a0eb71
Running extractors: favicon, title, headers, wget, screenshot
Output directory: /path/to/data/archive/1762193664373_example.com
  ✓ favicon: succeeded
  ✓ title: succeeded
  ✓ headers: succeeded
  ✓ wget: succeeded
  ✓ screenshot: succeeded
✓ Archiving complete!

# Check status
$ node dist/cli.js status 488ef9a8-fcd3-40c7-a209-3ab3b0a0eb71
Snapshot: 488ef9a8-fcd3-40c7-a209-3ab3b0a0eb71
URL: https://example.com
Title: Example Domain
Status: sealed
Created: 2025-11-03T18:14:04.279Z
Downloaded: 2025-11-03T18:14:25.273Z
Output: /path/to/data/archive/1762193664373_example.com

Archive Results (5):
  ✓ favicon: succeeded
    Output: favicon.ico
  ✓ title: succeeded
    Output: title.txt
  ✓ headers: succeeded
    Output: headers.json
  ✓ wget: succeeded
    Output: warc/archive.warc.gz
  ✓ screenshot: succeeded
    Output: screenshot.png

# List all snapshots
$ node dist/cli.js list
Found 1 snapshot(s):

ID: 488ef9a8-fcd3-40c7-a209-3ab3b0a0eb71
URL: https://example.com
Title: Example Domain
Status: sealed
Created: 2025-11-03T18:14:04.279Z
Output: /path/to/data/archive/1762193664373_example.com
---
```

## Creating Your First Extractor

Create a simple bash extractor:

```bash
# Create the extractor file
cat > extractors/myextractor << 'EOF'
#!/bin/bash
set -e

URL="$1"
if [ -z "$URL" ]; then
  echo "Error: URL required" >&2
  exit 1
fi

echo "Processing $URL..." >&2
echo "Hello from myextractor!" > output.txt
echo "✓ Done" >&2
echo "output.txt"
EOF

# Make it executable
chmod +x extractors/myextractor

# Test it
node dist/cli.js add "https://example.com" --extractors myextractor
```

See [EXTRACTOR_GUIDE.md](EXTRACTOR_GUIDE.md) for detailed information on creating extractors.

## Troubleshooting

### "No extractors available"

Make sure the extractor files are executable:
```bash
chmod +x extractors/*
```

### "Extractor failed"

Check the error message in the status output:
```bash
node dist/cli.js status <snapshot-id>
```

Common issues:
- Missing dependencies (extractor should auto-install)
- Network timeout (increase timeout via environment variable)
- Invalid URL format

### "Database locked"

Only one CLI command can run at a time. Wait for the current command to finish.

## Next Steps

- Read the [README.md](README.md) for architecture details
- Check out [EXTRACTOR_GUIDE.md](EXTRACTOR_GUIDE.md) to create custom extractors
- Browse the `extractors/` directory for examples
- Explore the TypeScript source code in `src/`

## Performance Tips

1. **Parallel Archiving**: Run multiple CLI instances with different data directories
2. **Selective Extractors**: Use `--extractors` flag to only run needed extractors
3. **Adjust Timeouts**: Increase timeouts for slow sites via environment variables
4. **Large Sites**: Use wget extractor for comprehensive archiving

## Data Management

### Backup

```bash
# Backup database
cp data/index.sqlite3 data/index.sqlite3.backup

# Backup everything
tar czf archivebox-backup.tar.gz data/
```

### Export

```bash
# Export database to SQL
sqlite3 data/index.sqlite3 .dump > export.sql

# Query snapshots
sqlite3 data/index.sqlite3 "SELECT url, title, status FROM snapshots;"
```

### Clean Up

```bash
# Remove old archives (manual)
rm -rf data/archive/<old-timestamp>_*

# Remove from database
sqlite3 data/index.sqlite3 "DELETE FROM snapshots WHERE url = 'https://example.com';"
```

Happy archiving! 🎉
