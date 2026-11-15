# {py:mod}`archivebox.core.smart_folders`

```{py:module} archivebox.core.smart_folders
```

```{autodoc2-docstring} archivebox.core.smart_folders
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`RuleQuery <archivebox.core.smart_folders.RuleQuery>`
  - ```{autodoc2-docstring} archivebox.core.smart_folders.RuleQuery
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`model_fields <archivebox.core.smart_folders.model_fields>`
  - ```{autodoc2-docstring} archivebox.core.smart_folders.model_fields
    :summary:
    ```
* - {py:obj}`field_spec <archivebox.core.smart_folders.field_spec>`
  - ```{autodoc2-docstring} archivebox.core.smart_folders.field_spec
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CHILDREN_RULES <archivebox.core.smart_folders.CHILDREN_RULES>`
  - ```{autodoc2-docstring} archivebox.core.smart_folders.CHILDREN_RULES
    :summary:
    ```
* - {py:obj}`OPERATORS <archivebox.core.smart_folders.OPERATORS>`
  - ```{autodoc2-docstring} archivebox.core.smart_folders.OPERATORS
    :summary:
    ```
* - {py:obj}`UNITS <archivebox.core.smart_folders.UNITS>`
  - ```{autodoc2-docstring} archivebox.core.smart_folders.UNITS
    :summary:
    ```
````

### API

````{py:data} CHILDREN_RULES
:canonical: archivebox.core.smart_folders.CHILDREN_RULES
:value: >
   None

```{autodoc2-docstring} archivebox.core.smart_folders.CHILDREN_RULES
```

````

````{py:data} OPERATORS
:canonical: archivebox.core.smart_folders.OPERATORS
:value: >
   None

```{autodoc2-docstring} archivebox.core.smart_folders.OPERATORS
```

````

````{py:data} UNITS
:canonical: archivebox.core.smart_folders.UNITS
:value: >
   None

```{autodoc2-docstring} archivebox.core.smart_folders.UNITS
```

````

````{py:function} model_fields()
:canonical: archivebox.core.smart_folders.model_fields

```{autodoc2-docstring} archivebox.core.smart_folders.model_fields
```
````

````{py:function} field_spec(name, field)
:canonical: archivebox.core.smart_folders.field_spec

```{autodoc2-docstring} archivebox.core.smart_folders.field_spec
```
````

`````{py:class} RuleQuery(folders=None, *, validate=False, freeze_limits=False)
:canonical: archivebox.core.smart_folders.RuleQuery

```{autodoc2-docstring} archivebox.core.smart_folders.RuleQuery
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.smart_folders.RuleQuery.__init__
```

````{py:method} sort_fields()
:canonical: archivebox.core.smart_folders.RuleQuery.sort_fields
:staticmethod:

```{autodoc2-docstring} archivebox.core.smart_folders.RuleQuery.sort_fields
```

````

````{py:method} ordering(folder)
:canonical: archivebox.core.smart_folders.RuleQuery.ordering
:classmethod:

```{autodoc2-docstring} archivebox.core.smart_folders.RuleQuery.ordering
```

````

````{py:method} limit(folder, query)
:canonical: archivebox.core.smart_folders.RuleQuery.limit

```{autodoc2-docstring} archivebox.core.smart_folders.RuleQuery.limit
```

````

````{py:method} schema()
:canonical: archivebox.core.smart_folders.RuleQuery.schema
:staticmethod:

```{autodoc2-docstring} archivebox.core.smart_folders.RuleQuery.schema
```

````

````{py:method} folder(folder_id, stack=())
:canonical: archivebox.core.smart_folders.RuleQuery.folder

```{autodoc2-docstring} archivebox.core.smart_folders.RuleQuery.folder
```

````

````{py:method} compile(rules, stack=())
:canonical: archivebox.core.smart_folders.RuleQuery.compile

```{autodoc2-docstring} archivebox.core.smart_folders.RuleQuery.compile
```

````

`````
