# {py:mod}`archivebox.domains.exports`

```{py:module} archivebox.domains.exports
```

```{autodoc2-docstring} archivebox.domains.exports
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`captured_pages <archivebox.domains.exports.captured_pages>`
  - ```{autodoc2-docstring} archivebox.domains.exports.captured_pages
    :summary:
    ```
* - {py:obj}`_write_page <archivebox.domains.exports._write_page>`
  - ```{autodoc2-docstring} archivebox.domains.exports._write_page
    :summary:
    ```
* - {py:obj}`write_static_site <archivebox.domains.exports.write_static_site>`
  - ```{autodoc2-docstring} archivebox.domains.exports.write_static_site
    :summary:
    ```
* - {py:obj}`write_wacz_site <archivebox.domains.exports.write_wacz_site>`
  - ```{autodoc2-docstring} archivebox.domains.exports.write_wacz_site
    :summary:
    ```
* - {py:obj}`export_snapshots_to_directory <archivebox.domains.exports.export_snapshots_to_directory>`
  - ```{autodoc2-docstring} archivebox.domains.exports.export_snapshots_to_directory
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CSS_URL <archivebox.domains.exports.CSS_URL>`
  - ```{autodoc2-docstring} archivebox.domains.exports.CSS_URL
    :summary:
    ```
````

### API

````{py:data} CSS_URL
:canonical: archivebox.domains.exports.CSS_URL
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.domains.exports.CSS_URL
```

````

````{py:function} captured_pages(snapshots)
:canonical: archivebox.domains.exports.captured_pages

```{autodoc2-docstring} archivebox.domains.exports.captured_pages
```
````

````{py:function} _write_page(destination, snapshot_id, page_url, root, path, links, report_bytes)
:canonical: archivebox.domains.exports._write_page

```{autodoc2-docstring} archivebox.domains.exports._write_page
```
````

````{py:function} write_static_site(destination, snapshots, *, title, progress, max_bytes=0)
:canonical: archivebox.domains.exports.write_static_site

```{autodoc2-docstring} archivebox.domains.exports.write_static_site
```
````

````{py:function} write_wacz_site(destination, snapshots, *, title, progress)
:canonical: archivebox.domains.exports.write_wacz_site

```{autodoc2-docstring} archivebox.domains.exports.write_wacz_site
```
````

````{py:function} export_snapshots_to_directory(queryset, *, destination, format, max_bytes=None, progress=None, title='Snapshots')
:canonical: archivebox.domains.exports.export_snapshots_to_directory

```{autodoc2-docstring} archivebox.domains.exports.export_snapshots_to_directory
```
````
