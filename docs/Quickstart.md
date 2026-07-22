# Quickstart

<div align="center">
<img src="https://imgur.zervice.io/ZbHpEf8.jpg" width="30%"/>
</div>

▶️ *It only takes about 5 minutes to get up and running with ArchiveBox.*

ArchiveBox [officially supports](https://github.com/ArchiveBox/ArchiveBox/wiki/Install#supported-systems) **macOS**, **Ubuntu/Debian**, and **BSD**, but likely runs on many other systems.  You can run it on any system that supports **Docker** and/or Python. Windows *is not supported* unless you run it inside Docker Desktop, Docker in WSL2, or WSL2.

For more detailed Docker and Docker Compose-specific instructions, see the [[Docker]] page.

---

## 1. Set up ArchiveBox

Follow the [README Instructions](https://github.com/ArchiveBox/ArchiveBox#quickstart) for your platform to get archivebox set up.

## 2. Get your list of URLs to archive

Follow the links here to find instructions for exporting a list of URLs from each service.

 - [Pocket](https://github.com/ArchiveBox/pocket-exporter)
 - [Pinboard](https://pinboard.in/export/)
 - [Instapaper](https://instapaper.zendesk.com/hc/en-us/articles/30080578815245-Import-export-content-from-into-Instapaper)
 - [Reddit Saved Posts](https://github.com/csu/export-saved-reddit)
 - [Shaarli](https://www.mypersonnaldata.eu/shaarli/doc/Backup,-restore,-import-and-export.html#export-links-as)
 - [Unmark.it](http://help.unmark.it/import-export)
 - [Wallabag](https://doc.wallabag.org/en/user/import/wallabagv2.html)
 - [Chrome Bookmarks](https://support.google.com/chrome/answer/96816?hl=en)
 - [Firefox Bookmarks](https://support.mozilla.org/en-US/kb/export-firefox-bookmarks-to-backup-or-transfer)
 - [Safari Bookmarks](http://imgur.zervice.io/AtcvUZA.png)
 - [Opera Bookmarks](http://help.opera.com/Windows/12.10/en/importexport.html)
 - [Internet Explorer Bookmarks](https://support.microsoft.com/en-us/help/211089/how-to-import-and-export-the-internet-explorer-favorites-folder-to-a-32-bit-version-of-windows)
 - Chrome History: `./bin/export_browser_history.sh --chrome`
 - Firefox History: `./bin/export_browser_history.sh --firefox`
 - Safari History: `./bin/export_browser_history.sh --safari`
 - Other File or URL: (e.g. RSS feed url, text file path) pass as second argument in the next step

 (If any of these links are broken, please submit an issue and I'll fix it)

## 3. Add your URLs to the archive

Pass in URLs directly, import a list of links from a file, or import from a feed URL. All via stdin:
```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"
cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
printf '%s\n' "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/one}" > your_urls.txt
uv run --project "$project_dir" --no-sync archivebox add --plugins=parse_txt_urls < your_urls.txt
curl -fsSL "${ARCHIVEBOX_DOCS_URL_TWO:-https://example.com/two}" | uv run --project "$project_dir" --no-sync archivebox add --plugins=parse_txt_urls
uv run --project "$project_dir" --no-sync archivebox add --plugins=parse_txt_urls "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}"
uv run --project "$project_dir" --no-sync archivebox list --json
uv run --project "$project_dir" --no-sync archivebox status
uv run --project "$project_dir" --no-sync archivebox search example
```

## ✅ Done!

Open `./archive` to view your archive data in the filesystem.

You can also use the interactive Web UI to view/manage/add links to your archive:
```bash
docker_data="$(mktemp -d)"
docker run --rm -v "$docker_data:/data" archivebox-docs-ci init
docker run --rm -v "$docker_data:/data" archivebox-docs-ci add --plugins=parse_txt_urls 'https://example.com/'
docker run --rm -v "$docker_data:/data" archivebox-docs-ci list --json
compose_file="$(mktemp)"
printf 'services:\n  archivebox:\n    image: archivebox-docs-ci\n    volumes:\n      - %s:/data\n' "$docker_data" > "$compose_file"
docker compose -f "$compose_file" run --rm archivebox status
docker compose -f "$compose_file" run --rm archivebox server --help
docker run --rm -v "$docker_data:/data" archivebox-docs-ci server --help
docker version
```

---

**Next Steps:**

```bash
project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init; uv run --project "$project_dir" --no-sync archivebox help
```

 - Read [[Usage]] to learn about the various CLI and web UI functions
 - Read [[Configuration]] to learn about the various archive method options
 - Read [[Scheduled Archiving]] to learn how to set up automatic daily archiving
 - Read [[Publishing Your Archive]] if you want to host your archive for others to access online
 - Read [[Troubleshooting]] if you encounter any problems
