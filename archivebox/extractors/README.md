Truths about Extractors:

- Snapshot worker should handle:
    - opening chrome tab for the snapshot > ./cdp_ws.sock
    - waiting for the page to load
    - emitting the ARCHIVING events:
        - SNAPSHOT_SETUP
        - SNAPSHOT_STARTED
        - SNAPSHOT_BEFORE_BROWSER_LAUNCH
        - SNAPSHOT_AFTER_BROWSER_LAUNCH
        - SNAPSHOT_BEFORE_PAGE_LOAD
        - SNAPSHOT_AFTER_PAGE_LOAD
        - SNAPSHOT_AFTER_NETWORK_IDLE2
    - extracting the page title
    - extracting all the outlinks
    - extracting all the search texts

- Extractor Worker should handle:
    - making sure any binaries the extractor depends on are installed and loaded
    - creating a new temporary working directory under the snapshot dir to hold extractor output
    - setting up a timer signal to kill the extractor if it runs too long
    - passing the extractor the URLs, temporary working directory, and config dict of options
    - running the extractor in a shell subprocess and collecting stdout/stderr
    - capturing the extractor's exit code
    - if extractor exits with 29 (RetryError), it should set the status to 'BACKOFF' and set retry_at to a datetime in the future
    - if extractor exits with 50 (NotApplicable), it should set the status to 'SKIPPED', and set retry_at to None
    - setting the correct permissions and ownership on all the output files
    - generating the merkle tree of all the output files and their hashes
    - generating a thumbnail of the main output (or collecting one provided by the extractor)
    - detecting any special outputs files that need to be parsed for other parts of the system (content-types? )
        - metadata.json -> ArchiveResult.output_json
        - outlinks.jsonl -> ArchiveResult.output_links
        - search_texts.txt -> ArchiveResult.index_texts
        - .merkle.json -> ArchiveResult.output_files
        - videos.jsonl -> ArchiveResult.output_videos
        - audios.jsonl -> ArchiveResult.output_audios
        - images.jsonl -> ArchiveResult.output_images
        - htmls.jsonl -> ArchiveResult.output_htmls
    - saving all the result metadata to the ArchiveResult in the database


- extractor takes a URL as a CLI arg, a current working directory, and env var options (or config benedict)
    - extractor should be able to see outputs in snapshot dir from extractors that ran before it
    - extractor should exit 0 for success, or non-zero for failure
    - extractor should exit 29 (RetryError) if it should be retried later (e.g. expected input is not ready yet, or got ratelimited, etc.)
    - extractor should exit 50 (NotApplicable) if it is unable to handle the given URL (e.g. if url is a file:/// but extractor only accepts https://youtube.com/*)
    - extractor should save output binary data files to the current working directory
    - extractor should output any logs text / progress to stdout, and error text to stderr
    - extractor should append any events it wants to emit as JSONL to the snapshot_dir/events.jsonl file. e.g.:
        - EXTRACTED_OUTLINK         {"url": "https://example.com", "title": "Example Domain", "selector": "a", "tags": ["link"], "timestamp": 1717305600}
        - EXTRACTED_SEARCH_TEXT     {"path": "articletext.txt", "record": archiveresult.id}
        - EXTRACTED_HTML            {"path": "index.html", "output_size": 123456, "mimetype": "text/html"}
        - EXTRACTED_SCREENSHOT      {"path": "screenshot.png", "output_size": 123456, "mimetype": "image/png"}
        - EXTRACTED_IMAGE           {"path": "favicon.ico", "output_size": 123456, "mimetype": "image/x-icon"}
        - EXTRACTED_VIDEO           {"path": "media/mainvideo.mp4", "output_size": 123456, "mimetype": "video/mp4"}
        - EXTRACTED_READABILITY     {"path": "readability.txt", "output_size": 123456, "mimetype": "text/plain"}
        - ...
    - extractor should save any JSON metadata detected to a special metadata.json file
    - extractor should create an index.html or symlink index.html to the main output file that the user will see
    - extractor should return the following str:
        - output_uri: str | None -> the URI of the main file or URL produced by the extractor (e.g. file:///path/to/index.html, https://web.archive.org/web/https:/..., file://./screenshot.png)
        - output_text: str | None -> the text content of the main output, if extractor primarily returns text
        - output_json: dict | None -> the structured Object returned by the extractor, if its main output is a JSON object
        - output_links: list[dict] -> a list of all the outlink URLs found during extraction {url, title, selector, tags, timestamp}
        - output_files: list[dict] -> the list of all the output files {path, hash_sha256, hash_blake3, size, mimetype}
        - output_thumbnail: str | None -> the URI of the thumbnail file, if any was created
        - output_html: str | None -> the path to the main HTML file if the extractor produces HTML


SNAPSHOT ARCHIVING EVENTS:
- SNAPSHOT_QUEUED
- SNAPSHOT_SETUP
- SNAPSHOT_STARTED
- SNAPSHOT_BEFORE_BROWSER_LAUNCH
- SNAPSHOT_AFTER_BROWSER_LAUNCH
- SNAPSHOT_BEFORE_PAGE_LOAD
- SNAPSHOT_AFTER_PAGE_LOAD
- SNAPSHOT_AFTER_NETWORK_IDLE2
- SNAPSHOT_BEFORE_SCREENSHOT
- SNAPSHOT_AFTER_SCREENSHOT
- SNAPSHOT_EXTRACT_ASYNC
- SNAPSHOT_EXTRACT_SYNC
- SNAPSHOT_EXTRACT_SHELL
- EXTRACTED_SCREENSHOT
- EXTRACTED_HEADERS
- EXTRACTED_HTML
- EXTRACTED_OUTLINKS
- EXTRACTED_DOWNLOADS
- EXTRACTED_AUDIO
- EXTRACTED_VIDEO
- EXTRACTED_IMAGE
- EXTRACTED_PDF
- EXTRACTED_TEXT
- EXTRACTED_SEARCH_TEXT
- SNAPSHOT_FINISHED
- SNAPSHOT_FAILED
- SNAPSHOT_RETRY
- SNAPSHOT_SKIPPED




- Standardized Output files:
    - .merkle.json -> ArchiveResult.output_files
    - outlinks.jsonl -> ArchiveResult.output_links
    - search_texts.txt -> ArchiveResult.index_texts
    - metadata.json -> ArchiveResult.output_json
    - thumbnail.png -> ArchiveResult.output_thumbnail
    - index.html -> ArchiveResult.output_html


class FaviconResult(ArchiveResult):
    dependencies: ClassVar[list[str]] = ['yt-dlp', 'curl', 'ffmpeg']
    context: ClassVar[str] = 'shell' | 'puppeteer'

    # snapshot: Snapshot
    # extractor: str
    # start_ts: datetime
    # end_ts: datetime
    # exit_code: int
    # stdout: str
    # stderr: str
    # cmd: list[str]
    # cmd_version: str
    # config: dict
    # status: str
    # retry_at: datetime | None

    # iface: NetworkInterface | None
    # machine: Machine | None
    # persona: Persona | None

    class Meta:
        verbose_name: str = 'Favicon'
        verbose_name_plural: str = 'Favicons'

    def save(...):
        # if not self.output_files:
        #     self.output_files = self.get_output_files()

    def get_cmd(self) -> list[str]:
        binary = archivebox.pm.hook.get_BINARY('curl')
        return [binary.name, '-fsSL', '-o', 'favicon.ico', domain_only(self.snapshot.url) + '/favicon.ico']

    def get_cmd_version(self) -> str:
        binary = archivebox.pm.hook.get_BINARY('curl')
        return binary.version

    def get_output_files(self) -> list[dict]:
        output_files = {}
        output_dirs = {}
        for path in self.OUTPUT_DIR.rglob('*'):
            if path.is_file():
                output_files[str(path.relative_to(self.OUTPUT_DIR))] = {
                    'path': str(path.relative_to(self.OUTPUT_DIR)),
                    'hash_sha256': hash_file(path, 'sha256'),
                    'hash_blake3': hash_file(path, 'blake3'),
                    'size': path.stat().st_size,
                    'mimetype': detect_mimetype(path),
                })
            else:
                output_dirs[str(path.relative_to(self.OUTPUT_DIR))] = {
                    'path': str(path.relative_to(self.OUTPUT_DIR)),
                    'hash_sha256': None,
                    'hash_blake3': None,
                    'size': None,
                    'mimetype': 'inode/directory',
                })

        for dir in output_dirs.values():
            subfiles = {path: file for path, file in output_files.items() if path.startswith(dir['path'])}
            dir['hash_sha256'] = hash_dir(dir['path'], 'sha256', subfiles)
            dir['hash_blake3'] = hash_dir(dir['path'], 'blake3', subfiles)
            dir['size'] = sum(file['size'] for file in subfiles.values())

        return {**output_files, **output_dirs}

    def get_output_text(self) -> str | None:
        return 'favicon.ico'

    def get_indexable_text(self) -> str | None:
        return ''

    def get_thumbnail(self) -> str | None:
        width, height = get_image_dimensions(self.OUTPUT_DIR / 'favicon.png')
        return {
            'path': self.favicon_uri,
            'abspath': self.OUTPUT_DIR / self.favicon_uri,
            'width': width,
            'height': height,
            'mimetype': 'image/png',
            'extension': 'png',
        }

    def get_icon(self) -> str | None:
        return self.get_thumbnail()


    def migrate_from_0_7_2(self) -> None:
        """Migrate output_dir generated by ArchiveBox <= 0.7.2 to current version"""
        print(f'{type(self).__name__}[{self.ABID}].migrate_from_0_7_2()')
        # move favicon.png -> self.OUTPUT_DIR / favicon.png



Migration:
    - For each ArchiveResult:
        - move it into subdir under name of the extractor + rename if needed
        - calculate merkle tree of all files in the output_dir
        - save the merkle tree to .merkle.json
        - symlink old location -> new location for backwards compatibility
    - For each Snapshot:
        - move data/archive/<timestamp> -> data/archive/snapshots/<abid>
        - symlink old location -> new location        


class TitleResult(ArchiveResult):
    dependencies: ClassVar[list[str]] = ['chrome', 'puppeteer']
    context: ClassVar[str] = 'puppeteer'


