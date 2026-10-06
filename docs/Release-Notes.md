## Changes since v0.9.71

**Four new plugins for cloud documents, shared folders, and better mobile replay — plus faster large archives and a more useful file browser.**

- 📄 **Save Google Docs, Sheets, Slides, and Drawings in everyday file formats.** The new [Google Docs plugin](https://plugins.archivebox.io/#googledocs) exports DOCX, XLSX, PPTX, CSV, PDF, SVG, and more. Public documents work without signing in; private documents use your capture persona's existing Google login, with no API keys or separate OAuth setup. Spreadsheets preserve every worksheet, with a sheet selector and format buttons in the embedded viewer.
- 📁 **Archive Google Drive folders.** The new [Google Drive plugin](https://plugins.archivebox.io/#googledrive) saves shared folders, including nested contents, using Drive's own download feature. Files are stored unpacked in their original folder structure, ready to browse, download, and search.
- 📦 **Save Dropbox shares, too.** The new [Dropbox plugin](https://plugins.archivebox.io/#dropbox) captures shared files and folders through your existing browser session. Folder contents are saved as ordinary files; the temporary download ZIP isn't kept as a second copy.
- 📱 **Fewer broken images when replaying on a phone.** The new [Mobile Size plugin](https://plugins.archivebox.io/#mobilesize) briefly visits a phone-width layout after saving desktop outputs, giving the archive a chance to capture additional responsive images and other resources. Your desktop screenshot and PDF stay at their original size. Replay can also recover some missing responsive images by using another archived image from the page's `srcset`.
- 🗂️ **A proper file explorer inside your archives.** Browse compact, full-width file lists with separate name, size, and type columns. Sort by any column, filter filenames instantly, and download individual files or folders. Small images and text files get inline previews. Saved ZIP files can also be browsed without loading the whole archive into your browser.
- 🔎 **Search inside cloud exports.** When enabled, LiteParse extracts text and OCRs images from Google Docs, Drive, and Dropbox outputs, including images embedded in supported document exports. Saved text and extracted content are available to Sonic search, so useful material doesn't stay hidden inside a folder download.
- ⚡ **More responsive large collections.** Queuing new URLs avoids waiting on slow archive storage. Browsing capture details and processing large queues is faster, and long-running captures use less memory. Linux hosts also avoid unnecessarily throttling captures when memory is still available.
- 🗑️ **Bulk deletion without tying up the page.** Snapshot deletion runs in the background, including cleanup on remote storage. If file removal fails, the snapshot stays tracked for another attempt rather than disappearing from the database while its files remain behind.
- 🔐 **More dependable private-page captures.** Cookie and authentication files resolve correctly relative to the collection, persona names are handled consistently, and missing optional cookie files no longer prevent browser startup.
- 🛠️ **More reliable capture and recovery.** Fixes improve SingleFile and WACZ downloads, PDF text extraction, and handling of cloud-folder links. Rescanning older archives recovers previously missing results, and pages with no captured discussion no longer show an empty forum card.

### 📸 See it in action

**Google Sheets: switch formats, select a worksheet, and read the saved data directly in ArchiveBox.**

![Archived Google Sheets data with XLSX, CSV, and PDF buttons and a worksheet selector](https://archivebox.io/screenshots/snapshot-view-googledocs-desktop.png)

**Google Drive: browse the actual saved files, with previews, sortable columns, filtering, and downloads.**

![Archived Google Drive folder in the file explorer, showing subfolders, a text preview, an image preview, and download buttons](https://archivebox.io/screenshots/snapshot-view-googledrive-desktop.png)

<details>
<summary>📦 Dropbox and 📱 Mobile Size screenshots</summary>

**Dropbox: shared-folder contents are immediately browsable as ordinary files.**

![Archived Dropbox folder showing saved image files and individual download buttons](https://archivebox.io/screenshots/snapshot-view-dropbox-desktop.png)

**Mobile Size: adjust the supplementary capture viewport in Add URLs or Persona settings under Page Setup.**

![Mobile Size settings expanded in the Add URLs plugin configuration](https://archivebox.io/screenshots/mobile-size-configuration-desktop.png)

</details>

[Explore more examples in the desktop, tablet, and mobile gallery](https://archivebox.io/screenshots/) or [browse all plugins](https://plugins.archivebox.io/).
