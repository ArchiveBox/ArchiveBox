# Extractor Development Guide

This guide explains how to create custom extractors for ArchiveBox-TS.

## What is an Extractor?

An extractor is a standalone executable program that:
1. Takes a URL as input
2. Processes/downloads content from that URL
3. Saves output files to the current directory
4. Reports success/failure via exit code

## Extractor Contract

Every extractor must follow these rules:

### 1. File Location
- Place the extractor file in the `extractors/` directory
- The filename becomes the extractor name (e.g., `extractors/myextractor` → `myextractor`)

### 2. Executable Permissions
```bash
chmod +x extractors/myextractor
```

### 3. Shebang Line
Start your file with the appropriate shebang:
- Bash: `#!/bin/bash`
- Node.js: `#!/usr/bin/env node`
- Python: `#!/usr/bin/env python3`
- Ruby: `#!/usr/bin/env ruby`
- Any other: `#!/usr/bin/env <interpreter>`

### 4. URL Input
The URL is passed as the first command-line argument:
- Bash: `$1`
- Node.js: `process.argv[2]`
- Python: `sys.argv[1]`

### 5. Output Directory
The extractor runs in the output directory. Write all files to the current directory (`.`).

### 6. Configuration
All configuration via environment variables:
- Read config: `${VAR_NAME:-default}` (bash) or `process.env.VAR_NAME` (Node.js)
- Name variables after your extractor: `MYEXTRACTOR_TIMEOUT`, `MYEXTRACTOR_WIDTH`, etc.
- Provide sensible defaults

### 7. Standard Output (stdout)
Print the main output file path to stdout:
```bash
echo "output.html"
```

### 8. Standard Error (stderr)
Use stderr for all logging, progress, and error messages:
```bash
echo "Downloading..." >&2
echo "Error: Failed" >&2
```

### 9. Exit Code
- `0` = Success
- Non-zero = Failure

### 10. Auto-Install Dependencies (Optional)
Your extractor can check for and install its dependencies:

```bash
if ! command -v mytool &> /dev/null; then
  echo "Installing mytool..." >&2
  # Install command here
fi
```

## Complete Examples

### Bash Extractor: HTML Downloader

```bash
#!/bin/bash
#
# HTML Extractor
# Downloads the raw HTML of a page
#
# Config:
#   HTML_TIMEOUT - Timeout in seconds (default: 30)
#   HTML_USER_AGENT - User agent string
#

set -e  # Exit on error

URL="$1"

# Validate input
if [ -z "$URL" ]; then
  echo "Error: URL argument required" >&2
  exit 1
fi

# Auto-install curl if needed
if ! command -v curl &> /dev/null; then
  echo "Installing curl..." >&2
  sudo apt-get update && sudo apt-get install -y curl
fi

# Read config from environment
TIMEOUT="${HTML_TIMEOUT:-30}"
USER_AGENT="${HTML_USER_AGENT:-Mozilla/5.0 (compatible; ArchiveBox-TS/0.1)}"

# Log to stderr
echo "Downloading HTML from: $URL" >&2

# Download HTML
if curl -L -s --max-time "$TIMEOUT" --user-agent "$USER_AGENT" -o index.html "$URL"; then
  echo "✓ Downloaded HTML" >&2
  echo "index.html"  # Output file to stdout
  exit 0
else
  echo "Error: Failed to download HTML" >&2
  exit 1
fi
```

### Node.js Extractor: JSON Metadata

```javascript
#!/usr/bin/env node
//
// Metadata Extractor
// Extracts metadata from a page and saves as JSON
//
// Config:
//   METADATA_TIMEOUT - Timeout in milliseconds (default: 10000)
//

const https = require('https');
const http = require('http');
const fs = require('fs');
const { URL } = require('url');

// Get URL from first argument
const url = process.argv[2];
if (!url) {
  console.error('Error: URL argument required');
  process.exit(1);
}

// Configuration
const TIMEOUT = parseInt(process.env.METADATA_TIMEOUT || '10000', 10);

console.error(`Extracting metadata from: ${url}`);

// Parse URL
let parsedUrl;
try {
  parsedUrl = new URL(url);
} catch (err) {
  console.error(`Error: Invalid URL: ${err.message}`);
  process.exit(1);
}

// Choose protocol
const client = parsedUrl.protocol === 'https:' ? https : http;

// Make request
const options = {
  timeout: TIMEOUT,
  headers: {
    'User-Agent': 'Mozilla/5.0 (compatible; ArchiveBox-TS/0.1)'
  }
};

client.get(url, options, (res) => {
  let html = '';

  res.on('data', (chunk) => {
    html += chunk;
  });

  res.on('end', () => {
    // Extract metadata
    const metadata = {
      url: url,
      status: res.statusCode,
      headers: res.headers,
      title: extractTitle(html),
      description: extractMeta(html, 'description'),
      keywords: extractMeta(html, 'keywords'),
      author: extractMeta(html, 'author'),
      timestamp: new Date().toISOString()
    };

    // Write to file
    fs.writeFileSync('metadata.json', JSON.stringify(metadata, null, 2));

    console.error('✓ Extracted metadata');
    console.log('metadata.json');
    process.exit(0);
  });
}).on('error', (err) => {
  console.error(`Error: ${err.message}`);
  process.exit(1);
});

function extractTitle(html) {
  const match = html.match(/<title[^>]*>(.*?)<\/title>/is);
  return match ? match[1].trim() : null;
}

function extractMeta(html, name) {
  const regex = new RegExp(`<meta[^>]*name=["']${name}["'][^>]*content=["']([^"']*)["']`, 'i');
  const match = html.match(regex);
  return match ? match[1] : null;
}
```

### Python Extractor: Link Extractor

```python
#!/usr/bin/env python3
#
# Links Extractor
# Extracts all links from a page
#
# Config:
#   LINKS_TIMEOUT - Timeout in seconds (default: 30)
#   LINKS_MAX - Maximum links to extract (default: 1000)
#

import sys
import os
import subprocess
import re
from urllib.request import urlopen, Request
from urllib.parse import urljoin, urlparse

def ensure_deps():
    """Auto-install dependencies"""
    # For this simple example, we use stdlib only
    pass

def main():
    # Validate input
    if len(sys.argv) < 2:
        print("Error: URL argument required", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]

    # Configuration
    timeout = int(os.environ.get('LINKS_TIMEOUT', '30'))
    max_links = int(os.environ.get('LINKS_MAX', '1000'))

    print(f"Extracting links from: {url}", file=sys.stderr)

    ensure_deps()

    try:
        # Fetch HTML
        req = Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; ArchiveBox-TS/0.1)'
        })
        with urlopen(req, timeout=timeout) as response:
            html = response.read().decode('utf-8', errors='ignore')

        # Extract links using regex (simple approach)
        # In production, use BeautifulSoup or lxml
        links = set()

        # Find <a href="...">
        for match in re.finditer(r'<a[^>]+href=["\'](.*?)["\']', html, re.IGNORECASE):
            href = match.group(1)
            # Convert relative to absolute
            absolute_url = urljoin(url, href)
            links.add(absolute_url)

            if len(links) >= max_links:
                break

        # Write to file
        with open('links.txt', 'w') as f:
            for link in sorted(links):
                f.write(link + '\n')

        print(f"✓ Extracted {len(links)} links", file=sys.stderr)
        print("links.txt")
        sys.exit(0)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
```

## Testing Your Extractor

### Manual Testing

1. Create a test directory:
```bash
mkdir test-output
cd test-output
```

2. Run your extractor:
```bash
/path/to/extractors/myextractor "https://example.com"
```

3. Check output:
```bash
ls -la
cat output-file.txt
```

### Environment Variable Testing

```bash
# Set config
export MYEXTRACTOR_TIMEOUT=60
export MYEXTRACTOR_DEBUG=true

# Run
/path/to/extractors/myextractor "https://example.com"
```

### Error Handling Testing

Test your extractor with:
- Invalid URLs
- URLs that timeout
- URLs that return 404
- URLs with special characters
- Very large pages
- Redirects

## Best Practices

### 1. Error Handling
- Always validate the URL argument
- Handle network errors gracefully
- Provide clear error messages to stderr
- Exit with non-zero code on failure

### 2. Timeouts
- Always set timeouts for network requests
- Make timeouts configurable via environment variables
- Use reasonable defaults (10-60 seconds)

### 3. Output
- Create files with clear, descriptive names
- Use standard formats (JSON, HTML, TXT, PNG, etc.)
- Print the main output filename to stdout
- If multiple files, print the primary one or a summary file

### 4. Logging
- Log progress to stderr
- Use prefixes: `✓` for success, `✗` for errors, `→` for progress
- Include URL in log messages
- Don't be too verbose (user can redirect if needed)

### 5. Performance
- Stream large files, don't load everything in memory
- Use parallel downloads when appropriate
- Respect robots.txt (optional but recommended)
- Add delays for rate limiting if needed

### 6. Configuration
- Use descriptive environment variable names
- Prefix with your extractor name: `MYEXT_VAR_NAME`
- Provide defaults for all settings
- Document all config options in comments

### 7. Dependencies
- Auto-install common dependencies when possible
- Detect OS and use appropriate package manager
- Provide clear error if dependency can't be installed
- Test with fresh environment

### 8. Idempotency
- Running twice should produce the same result
- Overwrite existing files
- Don't append to files

### 9. Security
- Validate and sanitize URLs
- Don't execute arbitrary code from fetched content
- Be careful with file paths (prevent directory traversal)
- Limit resource usage (file size, memory, etc.)

## Common Patterns

### Retry Logic

```bash
MAX_RETRIES=3
RETRY_DELAY=2

for i in $(seq 1 $MAX_RETRIES); do
  if download_url "$URL"; then
    break
  fi

  if [ $i -lt $MAX_RETRIES ]; then
    echo "Retry $i/$MAX_RETRIES in ${RETRY_DELAY}s..." >&2
    sleep $RETRY_DELAY
  fi
done
```

### Progress Reporting

```javascript
const total = 100;
let done = 0;

function updateProgress() {
  done++;
  console.error(`Progress: ${done}/${total} (${Math.round(done/total*100)}%)`);
}
```

### Conditional Extraction

```python
# Only extract if page is HTML
content_type = response.headers.get('content-type', '')
if 'text/html' not in content_type.lower():
    print(f"Skipping non-HTML content: {content_type}", file=sys.stderr)
    sys.exit(0)  # Success but skipped
```

## Debugging

### Enable Verbose Output

Add a DEBUG environment variable:

```bash
if [ "${MYEXT_DEBUG}" = "true" ]; then
  set -x  # Print commands
fi
```

### Test in Isolation

```bash
# Run in a clean environment
env -i \
  PATH=/usr/bin:/bin \
  MYEXT_TIMEOUT=30 \
  /path/to/extractors/myextractor "https://example.com"
```

### Check Exit Codes

```bash
/path/to/extractors/myextractor "https://example.com"
echo "Exit code: $?"
```

## Examples of Extractor Ideas

- **RSS Feed**: Extract RSS/Atom feed
- **Images**: Download all images from page
- **Video**: Extract video using yt-dlp
- **Archive.org**: Submit to Internet Archive
- **PDF**: Convert page to PDF using wkhtmltopdf
- **Reader Mode**: Extract main content using readability
- **Git**: Clone git repository
- **Twitter Thread**: Unroll and save thread
- **Mastodon Post**: Archive toot with media
- **GitHub Repo**: Archive repository with stars/forks
- **HackerNews Thread**: Save discussion thread
- **Reddit Thread**: Archive post and comments

## Next Steps

1. Create your extractor file in `extractors/`
2. Make it executable: `chmod +x extractors/yourextractor`
3. Test it manually
4. Use it with archivebox-ts: `node dist/cli.js add --extractors yourextractor https://example.com`

Happy extracting! 🎉
