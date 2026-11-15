# {py:mod}`archivebox.memento.views`

```{py:module} archivebox.memento.views
```

```{autodoc2-docstring} archivebox.memento.views
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_captures <archivebox.memento.views._captures>`
  - ```{autodoc2-docstring} archivebox.memento.views._captures
    :summary:
    ```
* - {py:obj}`_links <archivebox.memento.views._links>`
  - ```{autodoc2-docstring} archivebox.memento.views._links
    :summary:
    ```
* - {py:obj}`_archive_type <archivebox.memento.views._archive_type>`
  - ```{autodoc2-docstring} archivebox.memento.views._archive_type
    :summary:
    ```
* - {py:obj}`_enclosures <archivebox.memento.views._enclosures>`
  - ```{autodoc2-docstring} archivebox.memento.views._enclosures
    :summary:
    ```
* - {py:obj}`add_memento_headers <archivebox.memento.views.add_memento_headers>`
  - ```{autodoc2-docstring} archivebox.memento.views.add_memento_headers
    :summary:
    ```
* - {py:obj}`timemap_response <archivebox.memento.views.timemap_response>`
  - ```{autodoc2-docstring} archivebox.memento.views.timemap_response
    :summary:
    ```
* - {py:obj}`timegate_response <archivebox.memento.views.timegate_response>`
  - ```{autodoc2-docstring} archivebox.memento.views.timegate_response
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ARCHIVE_TYPES <archivebox.memento.views.ARCHIVE_TYPES>`
  - ```{autodoc2-docstring} archivebox.memento.views.ARCHIVE_TYPES
    :summary:
    ```
````

### API

````{py:data} ARCHIVE_TYPES
:canonical: archivebox.memento.views.ARCHIVE_TYPES
:value: >
   None

```{autodoc2-docstring} archivebox.memento.views.ARCHIVE_TYPES
```

````

````{py:function} _captures(request, url)
:canonical: archivebox.memento.views._captures

```{autodoc2-docstring} archivebox.memento.views._captures
```
````

````{py:function} _links(request, snapshot, relation='timemap')
:canonical: archivebox.memento.views._links

```{autodoc2-docstring} archivebox.memento.views._links
```
````

````{py:function} _archive_type(path)
:canonical: archivebox.memento.views._archive_type

```{autodoc2-docstring} archivebox.memento.views._archive_type
```
````

````{py:function} _enclosures(request, snapshot)
:canonical: archivebox.memento.views._enclosures

```{autodoc2-docstring} archivebox.memento.views._enclosures
```
````

````{py:function} add_memento_headers(request, snapshot, response, path='', primary=True)
:canonical: archivebox.memento.views.add_memento_headers

```{autodoc2-docstring} archivebox.memento.views.add_memento_headers
```
````

````{py:function} timemap_response(request, snapshot)
:canonical: archivebox.memento.views.timemap_response

```{autodoc2-docstring} archivebox.memento.views.timemap_response
```
````

````{py:function} timegate_response(request, url)
:canonical: archivebox.memento.views.timegate_response

```{autodoc2-docstring} archivebox.memento.views.timegate_response
```
````
