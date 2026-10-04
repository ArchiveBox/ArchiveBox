# Responsive-image replay regression

`google-drive.wacz` contains two unmodified, gzip-compressed WARC response
records from a real ArchiveWeb.page capture on 2026-10-04:

- https://drive.google.com/drive/folders/1KpLl_1tcK0eeehzN980zbG-3M2nhbVks
- https://www.gstatic.com/images/branding/productlogos/drive_2026/v1/web-48dp/logo_drive_2026_color_1x_web_48dp.png

The public folder's HTML declares both 1x and 2x logo URLs, but the recording
only contains the 1x image. These records were copied byte-for-byte from the
capture's `archive/data.warc.gz` using its CDX offsets; the subset CDX offsets and datapackage hashes were recomputed. No HTTP
responses were synthesized or edited. Other resources were omitted to keep the fixture small.
The test replays this actual archive at DPR 1 and 2, entirely from local storage.
