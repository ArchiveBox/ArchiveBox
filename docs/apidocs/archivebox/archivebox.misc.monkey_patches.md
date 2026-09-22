# {py:mod}`archivebox.misc.monkey_patches`

```{py:module} archivebox.misc.monkey_patches
```

```{autodoc2-docstring} archivebox.misc.monkey_patches
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ModifiedAccessLogGenerator <archivebox.misc.monkey_patches.ModifiedAccessLogGenerator>`
  - ```{autodoc2-docstring} archivebox.misc.monkey_patches.ModifiedAccessLogGenerator
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SENSITIVE_QUERY_PARAM_RE <archivebox.misc.monkey_patches.SENSITIVE_QUERY_PARAM_RE>`
  - ```{autodoc2-docstring} archivebox.misc.monkey_patches.SENSITIVE_QUERY_PARAM_RE
    :summary:
    ```
````

### API

````{py:data} SENSITIVE_QUERY_PARAM_RE
:canonical: archivebox.misc.monkey_patches.SENSITIVE_QUERY_PARAM_RE
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.misc.monkey_patches.SENSITIVE_QUERY_PARAM_RE
```

````

`````{py:class} ModifiedAccessLogGenerator(stream)
:canonical: archivebox.misc.monkey_patches.ModifiedAccessLogGenerator

Bases: {py:obj}`daphne.access.AccessLogGenerator`

```{autodoc2-docstring} archivebox.misc.monkey_patches.ModifiedAccessLogGenerator
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.misc.monkey_patches.ModifiedAccessLogGenerator.__init__
```

````{py:method} __call__(protocol, action, details)
:canonical: archivebox.misc.monkey_patches.ModifiedAccessLogGenerator.__call__

````

````{py:method} write_entry(host, date, request, status=None, length=None, ident=None, user=None, time_taken=None)
:canonical: archivebox.misc.monkey_patches.ModifiedAccessLogGenerator.write_entry

````

`````
