# {py:mod}`archivebox.misc.serve_static`

```{py:module} archivebox.misc.serve_static
```

```{autodoc2-docstring} archivebox.misc.serve_static
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_StreamingQueueWriter <archivebox.misc.serve_static._StreamingQueueWriter>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._StreamingQueueWriter
    :summary:
    ```
* - {py:obj}`RangedFileReader <archivebox.misc.serve_static.RangedFileReader>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.RangedFileReader
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_load_hash_map <archivebox.misc.serve_static._load_hash_map>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._load_hash_map
    :summary:
    ```
* - {py:obj}`_hash_for_path <archivebox.misc.serve_static._hash_for_path>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._hash_for_path
    :summary:
    ```
* - {py:obj}`_resolve_archive_path <archivebox.misc.serve_static._resolve_archive_path>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._resolve_archive_path
    :summary:
    ```
* - {py:obj}`_cache_policy <archivebox.misc.serve_static._cache_policy>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._cache_policy
    :summary:
    ```
* - {py:obj}`_render_mhtml_preview_document <archivebox.misc.serve_static._render_mhtml_preview_document>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._render_mhtml_preview_document
    :summary:
    ```
* - {py:obj}`_format_direntry_timestamp <archivebox.misc.serve_static._format_direntry_timestamp>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._format_direntry_timestamp
    :summary:
    ```
* - {py:obj}`_safe_zip_stem <archivebox.misc.serve_static._safe_zip_stem>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._safe_zip_stem
    :summary:
    ```
* - {py:obj}`_iter_visible_files <archivebox.misc.serve_static._iter_visible_files>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._iter_visible_files
    :summary:
    ```
* - {py:obj}`_build_directory_zip_response <archivebox.misc.serve_static._build_directory_zip_response>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._build_directory_zip_response
    :summary:
    ```
* - {py:obj}`_stream_ranged_file_async <archivebox.misc.serve_static._stream_ranged_file_async>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._stream_ranged_file_async
    :summary:
    ```
* - {py:obj}`_render_directory_index <archivebox.misc.serve_static._render_directory_index>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._render_directory_index
    :summary:
    ```
* - {py:obj}`_extract_markdown_candidate <archivebox.misc.serve_static._extract_markdown_candidate>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._extract_markdown_candidate
    :summary:
    ```
* - {py:obj}`_looks_like_markdown <archivebox.misc.serve_static._looks_like_markdown>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._looks_like_markdown
    :summary:
    ```
* - {py:obj}`_render_text_preview_document <archivebox.misc.serve_static._render_text_preview_document>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._render_text_preview_document
    :summary:
    ```
* - {py:obj}`_render_image_preview_document <archivebox.misc.serve_static._render_image_preview_document>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._render_image_preview_document
    :summary:
    ```
* - {py:obj}`_render_markdown_fallback <archivebox.misc.serve_static._render_markdown_fallback>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._render_markdown_fallback
    :summary:
    ```
* - {py:obj}`_render_markdown_document <archivebox.misc.serve_static._render_markdown_document>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._render_markdown_document
    :summary:
    ```
* - {py:obj}`_content_type_base <archivebox.misc.serve_static._content_type_base>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._content_type_base
    :summary:
    ```
* - {py:obj}`_is_risky_replay_document <archivebox.misc.serve_static._is_risky_replay_document>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._is_risky_replay_document
    :summary:
    ```
* - {py:obj}`_apply_archive_replay_headers <archivebox.misc.serve_static._apply_archive_replay_headers>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._apply_archive_replay_headers
    :summary:
    ```
* - {py:obj}`_is_asgi_request <archivebox.misc.serve_static._is_asgi_request>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._is_asgi_request
    :summary:
    ```
* - {py:obj}`serve_static_with_byterange_support <archivebox.misc.serve_static.serve_static_with_byterange_support>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.serve_static_with_byterange_support
    :summary:
    ```
* - {py:obj}`serve_static <archivebox.misc.serve_static.serve_static>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.serve_static
    :summary:
    ```
* - {py:obj}`parse_range_header <archivebox.misc.serve_static.parse_range_header>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.parse_range_header
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_HASHES_CACHE <archivebox.misc.serve_static._HASHES_CACHE>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static._HASHES_CACHE
    :summary:
    ```
* - {py:obj}`MARKDOWN_INLINE_LINK_RE <archivebox.misc.serve_static.MARKDOWN_INLINE_LINK_RE>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.MARKDOWN_INLINE_LINK_RE
    :summary:
    ```
* - {py:obj}`MARKDOWN_INLINE_IMAGE_RE <archivebox.misc.serve_static.MARKDOWN_INLINE_IMAGE_RE>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.MARKDOWN_INLINE_IMAGE_RE
    :summary:
    ```
* - {py:obj}`MARKDOWN_BOLD_RE <archivebox.misc.serve_static.MARKDOWN_BOLD_RE>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.MARKDOWN_BOLD_RE
    :summary:
    ```
* - {py:obj}`MARKDOWN_ITALIC_RE <archivebox.misc.serve_static.MARKDOWN_ITALIC_RE>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.MARKDOWN_ITALIC_RE
    :summary:
    ```
* - {py:obj}`HTML_TAG_RE <archivebox.misc.serve_static.HTML_TAG_RE>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.HTML_TAG_RE
    :summary:
    ```
* - {py:obj}`HTML_BODY_RE <archivebox.misc.serve_static.HTML_BODY_RE>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.HTML_BODY_RE
    :summary:
    ```
* - {py:obj}`RISKY_REPLAY_MIMETYPES <archivebox.misc.serve_static.RISKY_REPLAY_MIMETYPES>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.RISKY_REPLAY_MIMETYPES
    :summary:
    ```
* - {py:obj}`RISKY_REPLAY_EXTENSIONS <archivebox.misc.serve_static.RISKY_REPLAY_EXTENSIONS>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.RISKY_REPLAY_EXTENSIONS
    :summary:
    ```
* - {py:obj}`RISKY_REPLAY_MARKERS <archivebox.misc.serve_static.RISKY_REPLAY_MARKERS>`
  - ```{autodoc2-docstring} archivebox.misc.serve_static.RISKY_REPLAY_MARKERS
    :summary:
    ```
````

### API

````{py:data} _HASHES_CACHE
:canonical: archivebox.misc.serve_static._HASHES_CACHE
:type: dict[pathlib.Path, tuple[float, dict[str, str]]]
:value: >
   None

```{autodoc2-docstring} archivebox.misc.serve_static._HASHES_CACHE
```

````

````{py:function} _load_hash_map(snapshot_dir: pathlib.Path) -> dict[str, str] | None
:canonical: archivebox.misc.serve_static._load_hash_map

```{autodoc2-docstring} archivebox.misc.serve_static._load_hash_map
```
````

````{py:function} _hash_for_path(document_root: pathlib.Path, rel_path: str) -> str | None
:canonical: archivebox.misc.serve_static._hash_for_path

```{autodoc2-docstring} archivebox.misc.serve_static._hash_for_path
```
````

````{py:function} _resolve_archive_path(document_root: str | pathlib.Path, rel_path: str) -> tuple[pathlib.Path, str]
:canonical: archivebox.misc.serve_static._resolve_archive_path

```{autodoc2-docstring} archivebox.misc.serve_static._resolve_archive_path
```
````

````{py:function} _cache_policy(config=None, **config_kwargs) -> str
:canonical: archivebox.misc.serve_static._cache_policy

```{autodoc2-docstring} archivebox.misc.serve_static._cache_policy
```
````

````{py:function} _render_mhtml_preview_document(filename: str, output_path: str) -> str
:canonical: archivebox.misc.serve_static._render_mhtml_preview_document

```{autodoc2-docstring} archivebox.misc.serve_static._render_mhtml_preview_document
```
````

````{py:function} _format_direntry_timestamp(stat_result: os.stat_result) -> str
:canonical: archivebox.misc.serve_static._format_direntry_timestamp

```{autodoc2-docstring} archivebox.misc.serve_static._format_direntry_timestamp
```
````

````{py:function} _safe_zip_stem(name: str) -> str
:canonical: archivebox.misc.serve_static._safe_zip_stem

```{autodoc2-docstring} archivebox.misc.serve_static._safe_zip_stem
```
````

`````{py:class} _StreamingQueueWriter(output_queue: queue.Queue[bytes | BaseException | object])
:canonical: archivebox.misc.serve_static._StreamingQueueWriter

```{autodoc2-docstring} archivebox.misc.serve_static._StreamingQueueWriter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.misc.serve_static._StreamingQueueWriter.__init__
```

````{py:method} write(data: bytes) -> int
:canonical: archivebox.misc.serve_static._StreamingQueueWriter.write

```{autodoc2-docstring} archivebox.misc.serve_static._StreamingQueueWriter.write
```

````

````{py:method} tell() -> int
:canonical: archivebox.misc.serve_static._StreamingQueueWriter.tell

```{autodoc2-docstring} archivebox.misc.serve_static._StreamingQueueWriter.tell
```

````

````{py:method} flush() -> None
:canonical: archivebox.misc.serve_static._StreamingQueueWriter.flush

```{autodoc2-docstring} archivebox.misc.serve_static._StreamingQueueWriter.flush
```

````

````{py:method} close() -> None
:canonical: archivebox.misc.serve_static._StreamingQueueWriter.close

```{autodoc2-docstring} archivebox.misc.serve_static._StreamingQueueWriter.close
```

````

````{py:method} writable() -> bool
:canonical: archivebox.misc.serve_static._StreamingQueueWriter.writable

```{autodoc2-docstring} archivebox.misc.serve_static._StreamingQueueWriter.writable
```

````

````{py:method} seekable() -> bool
:canonical: archivebox.misc.serve_static._StreamingQueueWriter.seekable

```{autodoc2-docstring} archivebox.misc.serve_static._StreamingQueueWriter.seekable
```

````

`````

````{py:function} _iter_visible_files(root: pathlib.Path)
:canonical: archivebox.misc.serve_static._iter_visible_files

```{autodoc2-docstring} archivebox.misc.serve_static._iter_visible_files
```
````

````{py:function} _build_directory_zip_response(fullpath: pathlib.Path, path: str, *, is_archive_replay: bool, use_async_stream: bool, config=None) -> django.http.StreamingHttpResponse
:canonical: archivebox.misc.serve_static._build_directory_zip_response

```{autodoc2-docstring} archivebox.misc.serve_static._build_directory_zip_response
```
````

````{py:function} _stream_ranged_file_async(ranged_file: RangedFileReader)
:canonical: archivebox.misc.serve_static._stream_ranged_file_async
:async:

```{autodoc2-docstring} archivebox.misc.serve_static._stream_ranged_file_async
```
````

````{py:function} _render_directory_index(request, path: str, fullpath: pathlib.Path) -> django.http.HttpResponse
:canonical: archivebox.misc.serve_static._render_directory_index

```{autodoc2-docstring} archivebox.misc.serve_static._render_directory_index
```
````

````{py:data} MARKDOWN_INLINE_LINK_RE
:canonical: archivebox.misc.serve_static.MARKDOWN_INLINE_LINK_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.misc.serve_static.MARKDOWN_INLINE_LINK_RE
```

````

````{py:data} MARKDOWN_INLINE_IMAGE_RE
:canonical: archivebox.misc.serve_static.MARKDOWN_INLINE_IMAGE_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.misc.serve_static.MARKDOWN_INLINE_IMAGE_RE
```

````

````{py:data} MARKDOWN_BOLD_RE
:canonical: archivebox.misc.serve_static.MARKDOWN_BOLD_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.misc.serve_static.MARKDOWN_BOLD_RE
```

````

````{py:data} MARKDOWN_ITALIC_RE
:canonical: archivebox.misc.serve_static.MARKDOWN_ITALIC_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.misc.serve_static.MARKDOWN_ITALIC_RE
```

````

````{py:data} HTML_TAG_RE
:canonical: archivebox.misc.serve_static.HTML_TAG_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.misc.serve_static.HTML_TAG_RE
```

````

````{py:data} HTML_BODY_RE
:canonical: archivebox.misc.serve_static.HTML_BODY_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.misc.serve_static.HTML_BODY_RE
```

````

````{py:data} RISKY_REPLAY_MIMETYPES
:canonical: archivebox.misc.serve_static.RISKY_REPLAY_MIMETYPES
:value: >
   None

```{autodoc2-docstring} archivebox.misc.serve_static.RISKY_REPLAY_MIMETYPES
```

````

````{py:data} RISKY_REPLAY_EXTENSIONS
:canonical: archivebox.misc.serve_static.RISKY_REPLAY_EXTENSIONS
:value: >
   None

```{autodoc2-docstring} archivebox.misc.serve_static.RISKY_REPLAY_EXTENSIONS
```

````

````{py:data} RISKY_REPLAY_MARKERS
:canonical: archivebox.misc.serve_static.RISKY_REPLAY_MARKERS
:value: >
   ('<!doctype html', '<html', '<svg')

```{autodoc2-docstring} archivebox.misc.serve_static.RISKY_REPLAY_MARKERS
```

````

````{py:function} _extract_markdown_candidate(text: str) -> str
:canonical: archivebox.misc.serve_static._extract_markdown_candidate

```{autodoc2-docstring} archivebox.misc.serve_static._extract_markdown_candidate
```
````

````{py:function} _looks_like_markdown(text: str) -> bool
:canonical: archivebox.misc.serve_static._looks_like_markdown

```{autodoc2-docstring} archivebox.misc.serve_static._looks_like_markdown
```
````

````{py:function} _render_text_preview_document(text: str, title: str) -> str
:canonical: archivebox.misc.serve_static._render_text_preview_document

```{autodoc2-docstring} archivebox.misc.serve_static._render_text_preview_document
```
````

````{py:function} _render_image_preview_document(image_url: str, title: str) -> str
:canonical: archivebox.misc.serve_static._render_image_preview_document

```{autodoc2-docstring} archivebox.misc.serve_static._render_image_preview_document
```
````

````{py:function} _render_markdown_fallback(text: str) -> str
:canonical: archivebox.misc.serve_static._render_markdown_fallback

```{autodoc2-docstring} archivebox.misc.serve_static._render_markdown_fallback
```
````

````{py:function} _render_markdown_document(markdown_text: str) -> str
:canonical: archivebox.misc.serve_static._render_markdown_document

```{autodoc2-docstring} archivebox.misc.serve_static._render_markdown_document
```
````

````{py:function} _content_type_base(content_type: str) -> str
:canonical: archivebox.misc.serve_static._content_type_base

```{autodoc2-docstring} archivebox.misc.serve_static._content_type_base
```
````

````{py:function} _is_risky_replay_document(fullpath: pathlib.Path, content_type: str) -> bool
:canonical: archivebox.misc.serve_static._is_risky_replay_document

```{autodoc2-docstring} archivebox.misc.serve_static._is_risky_replay_document
```
````

````{py:function} _apply_archive_replay_headers(response: django.http.HttpResponse, *, fullpath: pathlib.Path, content_type: str, is_archive_replay: bool, config=None, **config_kwargs) -> django.http.HttpResponse
:canonical: archivebox.misc.serve_static._apply_archive_replay_headers

```{autodoc2-docstring} archivebox.misc.serve_static._apply_archive_replay_headers
```
````

````{py:function} _is_asgi_request(request) -> bool
:canonical: archivebox.misc.serve_static._is_asgi_request

```{autodoc2-docstring} archivebox.misc.serve_static._is_asgi_request
```
````

````{py:function} serve_static_with_byterange_support(request, path, document_root=None, show_indexes=False, is_archive_replay: bool = False)
:canonical: archivebox.misc.serve_static.serve_static_with_byterange_support

```{autodoc2-docstring} archivebox.misc.serve_static.serve_static_with_byterange_support
```
````

````{py:function} serve_static(request, path, **kwargs)
:canonical: archivebox.misc.serve_static.serve_static

```{autodoc2-docstring} archivebox.misc.serve_static.serve_static
```
````

````{py:function} parse_range_header(header, resource_size)
:canonical: archivebox.misc.serve_static.parse_range_header

```{autodoc2-docstring} archivebox.misc.serve_static.parse_range_header
```
````

`````{py:class} RangedFileReader(file_like, start=0, stop=float('inf'), block_size=None)
:canonical: archivebox.misc.serve_static.RangedFileReader

```{autodoc2-docstring} archivebox.misc.serve_static.RangedFileReader
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.misc.serve_static.RangedFileReader.__init__
```

````{py:attribute} block_size
:canonical: archivebox.misc.serve_static.RangedFileReader.block_size
:value: >
   8192

```{autodoc2-docstring} archivebox.misc.serve_static.RangedFileReader.block_size
```

````

````{py:method} __iter__()
:canonical: archivebox.misc.serve_static.RangedFileReader.__iter__

```{autodoc2-docstring} archivebox.misc.serve_static.RangedFileReader.__iter__
```

````

````{py:method} close()
:canonical: archivebox.misc.serve_static.RangedFileReader.close

```{autodoc2-docstring} archivebox.misc.serve_static.RangedFileReader.close
```

````

`````
