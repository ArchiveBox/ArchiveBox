# JS Implementation Features to Port to Python ArchiveBox

## Priority: High Impact Features

### 1. **Screen Recording** ⭐⭐⭐
**JS Implementation:** Captures MP4 video + animated GIF of the archiving session
```javascript
// Records browser activity including scrolling, interactions
PuppeteerScreenRecorder → screenrecording.mp4
ffmpeg conversion → screenrecording.gif (first 10s, optimized)
```

**Enhancement for Python:**
- Add `on_Snapshot__24_screenrecording.py`
- Use puppeteer or playwright screen recording APIs
- Generate both full MP4 and thumbnail GIF
- **Value:** Visual proof of what was captured, useful for QA and debugging

### 2. **AI Quality Assurance** ⭐⭐⭐
**JS Implementation:** Uses GPT-4o to analyze screenshots and validate archive quality
```javascript
// ai_qa.py analyzes screenshot.png and returns:
{
  "pct_visible": 85,
  "warnings": ["Some content may be cut off"],
  "main_content_title": "Article Title",
  "main_content_author": "Author Name",
  "main_content_date": "2024-01-15",
  "website_brand_name": "Example.com"
}
```

**Enhancement for Python:**
- Add `on_Snapshot__95_aiqa.py` (runs after screenshot)
- Integrate with OpenAI API or local vision models
- Validates: content visibility, broken layouts, CAPTCHA blocks, error pages
- **Value:** Automatic detection of failed archives, quality scoring

### 3. **Network Response Archiving** ⭐⭐⭐
**JS Implementation:** Saves ALL network responses in organized structure
```
responses/
├── all/                          # Timestamped unique files
│   ├── 20240101120000__GET__https%3A%2F%2Fexample.com%2Fapi.json
│   └── ...
├── script/                       # Organized by resource type
│   └── example.com/path/to/script.js → ../all/...
├── stylesheet/
├── image/
├── media/
└── index.jsonl                   # Searchable index
```

**Enhancement for Python:**
- Add `on_Snapshot__23_responses.py`
- Save all HTTP responses (XHR, images, scripts, etc.)
- Create both timestamped and URL-organized views via symlinks
- Generate `index.jsonl` with metadata (URL, method, status, mimeType, sha256)
- **Value:** Complete HTTP-level archive, better debugging, API response preservation

### 4. **Detailed Metadata Extractors** ⭐⭐

#### 4a. SSL/TLS Details (`on_Snapshot__16_ssl.py`)
```python
{
  "protocol": "TLS 1.3",
  "cipher": "AES_128_GCM",
  "securityState": "secure",
  "securityDetails": {
    "issuer": "Let's Encrypt",
    "validFrom": ...,
    "validTo": ...
  }
}
```

#### 4b. SEO Metadata (`on_Snapshot__17_seo.py`)
Extracts all `<meta>` tags:
```python
{
  "og:title": "Page Title",
  "og:image": "https://example.com/image.jpg",
  "twitter:card": "summary_large_image",
  "description": "Page description",
  ...
}
```

#### 4c. Accessibility Tree (`on_Snapshot__18_accessibility.py`)
```python
{
  "headings": ["# Main Title", "## Section 1", ...],
  "iframes": ["https://embed.example.com/..."],
  "tree": { ... }  # Full accessibility snapshot
}
```

#### 4d. Outlinks Categorization (`on_Snapshot__19_outlinks.py`)
Better than current implementation - categorizes by type:
```python
{
  "hrefs": [...],           # All <a> links
  "images": [...],          # <img src>
  "css_stylesheets": [...], # <link rel=stylesheet>
  "js_scripts": [...],      # <script src>
  "iframes": [...],         # <iframe src>
  "css_images": [...],      # background-image: url()
  "links": [{...}]          # <link> tags (rel, href)
}
```

#### 4e. Redirects Chain (`on_Snapshot__15_redirects.py`)
Tracks full redirect sequence:
```python
{
  "redirects_from_http": [
    {"url": "http://ex.com", "status": 301, "isMainFrame": True},
    {"url": "https://ex.com", "status": 302, "isMainFrame": True},
    {"url": "https://www.ex.com", "status": 200, "isMainFrame": True}
  ]
}
```

**Value:** Rich metadata for research, SEO analysis, security auditing

### 5. **Enhanced Screenshot System** ⭐⭐
**JS Implementation:**
- `screenshot.png` - Full-page PNG at high resolution (4:3 ratio)
- `screenshot.jpg` - Compressed JPEG for thumbnails (1440x1080, 90% quality)
- Automatically crops to reasonable height for long pages

**Enhancement for Python:**
- Update `screenshot` extractor to generate both formats
- Use aspect ratio optimization (4:3 is better for thumbnails than 16:9)
- **Value:** Faster loading thumbnails, better storage efficiency

### 6. **Console Log Capture** ⭐⭐
**JS Implementation:**
```
console.log - Captures all console output
  ERROR /path/to/script.js:123 "Uncaught TypeError: ..."
  WARNING https://example.com/api Failed to load resource: net::ERR_BLOCKED_BY_CLIENT
```

**Enhancement for Python:**
- Add `on_Snapshot__20_consolelog.py`
- Useful for debugging JavaScript errors, tracking blocked resources
- **Value:** Identifies rendering issues, ad blockers, CORS problems

## Priority: Nice-to-Have Enhancements

### 7. **Request/Response Headers** ⭐
**Current:** Headers extractor exists but could be enhanced
**JS Enhancement:** Separates request vs response, includes extra headers

### 8. **Human Behavior Emulation** ⭐
**JS Implementation:**
- Mouse jiggling with ghost-cursor
- Smart scrolling with infinite scroll detection
- Comment expansion (Reddit, HackerNews, etc.)
- Form submission
- CAPTCHA solving via 2captcha extension

**Enhancement for Python:**
- Add `on_Snapshot__05_human_behavior.py` (runs BEFORE other extractors)
- Implement scrolling, clicking "Load More", expanding comments
- **Value:** Captures more content from dynamic sites

### 9. **CAPTCHA Solving** ⭐
**JS Implementation:** Integrates 2captcha extension
**Enhancement:** Add optional CAPTCHA solving via 2captcha API
**Value:** Access to Cloudflare-protected sites

### 10. **Source Map Downloading**
**JS Implementation:** Automatically downloads `.map` files for JS/CSS
**Enhancement:** Add `on_Snapshot__30_sourcemaps.py`
**Value:** Helps debug minified code

### 11. **Pandoc Markdown Conversion**
**JS Implementation:** Converts HTML ↔ Markdown using Pandoc
```bash
pandoc --from html --to markdown_github --wrap=none
```
**Enhancement:** Add `on_Snapshot__34_pandoc.py`
**Value:** Human-readable Markdown format

### 12. **Authentication Management** ⭐
**JS Implementation:**
- Sophisticated cookie storage with `cookies.txt` export
- LocalStorage + SessionStorage preservation
- Merge new cookies with existing ones (no overwrites)

**Enhancement:**
- Improve `auth.json` management to match JS sophistication
- Add `cookies.txt` export (Netscape format) for compatibility with wget/curl
- **Value:** Better session persistence across runs

### 13. **File Integrity & Versioning** ⭐⭐
**JS Implementation:**
- SHA256 hash for every file
- Merkle tree directory hashes
- Version directories (`versions/YYYYMMDDHHMMSS/`)
- Symlinks to latest versions
- `.files.json` manifest with metadata

**Enhancement:**
- Add `on_Snapshot__99_integrity.py` (runs last)
- Generate SHA256 hashes for all outputs
- Create version manifests
- **Value:** Verify archive integrity, detect corruption, track changes

### 14. **Directory Organization**
**JS Structure (superior):**
```
archive/<timestamp>/
├── versions/
│   ├── 20240101120000/         # Each run = new version
│   │   ├── screenshot.png
│   │   ├── singlefile.html
│   │   └── ...
│   └── 20240102150000/
├── screenshot.png → versions/20240102150000/screenshot.png  # Symlink to latest
├── singlefile.html → ...
└── metrics.json
```

**Current Python:** All outputs in flat structure
**Enhancement:** Add versioning layer for tracking changes over time

### 15. **Speedtest Integration**
**JS Implementation:** Runs fast.com speedtest once per day
**Enhancement:** Optional `on_Snapshot__01_speedtest.py`
**Value:** Diagnose slow archives, track connection quality

### 16. **gallery-dl Support** ⭐
**JS Implementation:** Downloads photo galleries (Instagram, Twitter, etc.)
**Enhancement:** Add `on_Snapshot__30_photos.py` alongside existing `media` extractor
**Value:** Better support for image-heavy sites

## Implementation Priority Ranking

### Must-Have (High ROI):
1. **Network Response Archiving** - Complete HTTP archive
2. **AI Quality Assurance** - Automatic validation
3. **Screen Recording** - Visual proof of capture
4. **Enhanced Metadata** (SSL, SEO, Accessibility, Outlinks) - Research value

### Should-Have (Medium ROI):
5. **Console Log Capture** - Debugging aid
6. **File Integrity Hashing** - Archive verification
7. **Enhanced Screenshots** - Better thumbnails
8. **Versioning System** - Track changes over time

### Nice-to-Have (Lower ROI):
9. **Human Behavior Emulation** - Dynamic content
10. **CAPTCHA Solving** - Access restricted sites
11. **gallery-dl** - Image collections
12. **Pandoc Markdown** - Readable format

## Technical Considerations

### Dependencies Needed:
- **Screen Recording:** `playwright` or `puppeteer` with recording API
- **AI QA:** `openai` Python SDK or local vision model
- **Network Archiving:** CDP protocol access (already have via Chrome)
- **File Hashing:** Built-in `hashlib` (no new deps)
- **gallery-dl:** Install via pip

### Performance Impact:
- Screen recording: +2-3 seconds overhead per snapshot
- AI QA: +0.5-2 seconds (API call) per snapshot
- Response archiving: Minimal (async writes)
- File hashing: +0.1-0.5 seconds per snapshot
- Metadata extraction: Minimal (same page visit)

### Architecture Compatibility:
All proposed enhancements fit the existing hook-based plugin architecture:
- Use standard `on_Snapshot__NN_name.py` naming
- Return `ExtractorResult` objects
- Can reuse shared Chrome CDP sessions
- Follow existing error handling patterns

## Summary Statistics

**JS Implementation:**
- 35+ output types
- ~3000 lines of archiving logic
- Extensive quality assurance
- Complete HTTP-level capture

**Current Python Implementation:**
- 12 extractors
- Strong foundation with room for enhancement

**Recommended Additions:**
- **8 new high-priority extractors**
- **6 enhanced versions of existing extractors**
- **3 optional nice-to-have extractors**

This would bring the Python implementation to feature parity with the JS version while maintaining better code organization and the existing plugin architecture.
