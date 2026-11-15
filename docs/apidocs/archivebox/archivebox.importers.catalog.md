# {py:mod}`archivebox.importers.catalog`

```{py:module} archivebox.importers.catalog
```

```{autodoc2-docstring} archivebox.importers.catalog
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ImporterDefinition <archivebox.importers.catalog.ImporterDefinition>`
  - ```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`get_importers <archivebox.importers.catalog.get_importers>`
  - ```{autodoc2-docstring} archivebox.importers.catalog.get_importers
    :summary:
    ```
* - {py:obj}`get_importer <archivebox.importers.catalog.get_importer>`
  - ```{autodoc2-docstring} archivebox.importers.catalog.get_importer
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`logger <archivebox.importers.catalog.logger>`
  - ```{autodoc2-docstring} archivebox.importers.catalog.logger
    :summary:
    ```
````

### API

````{py:data} logger
:canonical: archivebox.importers.catalog.logger
:value: >
   'getLogger(...)'

```{autodoc2-docstring} archivebox.importers.catalog.logger
```

````

`````{py:class} ImporterDefinition
:canonical: archivebox.importers.catalog.ImporterDefinition

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition
```

````{py:attribute} plugin
:canonical: archivebox.importers.catalog.ImporterDefinition.plugin
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.plugin
```

````

````{py:attribute} feed
:canonical: archivebox.importers.catalog.ImporterDefinition.feed
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.feed
```

````

````{py:attribute} provider
:canonical: archivebox.importers.catalog.ImporterDefinition.provider
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.provider
```

````

````{py:attribute} title
:canonical: archivebox.importers.catalog.ImporterDefinition.title
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.title
```

````

````{py:attribute} description
:canonical: archivebox.importers.catalog.ImporterDefinition.description
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.description
```

````

````{py:attribute} auth
:canonical: archivebox.importers.catalog.ImporterDefinition.auth
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.auth
```

````

````{py:attribute} fields
:canonical: archivebox.importers.catalog.ImporterDefinition.fields
:type: dict
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.fields
```

````

````{py:attribute} timeout
:canonical: archivebox.importers.catalog.ImporterDefinition.timeout
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.timeout
```

````

````{py:attribute} setup
:canonical: archivebox.importers.catalog.ImporterDefinition.setup
:type: tuple
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.setup
```

````

````{py:attribute} icon
:canonical: archivebox.importers.catalog.ImporterDefinition.icon
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.importers.catalog.ImporterDefinition.icon
```

````

`````

````{py:function} get_importers() -> dict[tuple[str, str], archivebox.importers.catalog.ImporterDefinition]
:canonical: archivebox.importers.catalog.get_importers

```{autodoc2-docstring} archivebox.importers.catalog.get_importers
```
````

````{py:function} get_importer(plugin: str, feed: str) -> archivebox.importers.catalog.ImporterDefinition
:canonical: archivebox.importers.catalog.get_importer

```{autodoc2-docstring} archivebox.importers.catalog.get_importer
```
````
