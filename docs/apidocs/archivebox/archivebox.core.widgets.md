# {py:mod}`archivebox.core.widgets`

```{py:module} archivebox.core.widgets
```

```{autodoc2-docstring} archivebox.core.widgets
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TagEditorWidget <archivebox.core.widgets.TagEditorWidget>`
  - ```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget
    :summary:
    ```
* - {py:obj}`URLFiltersWidget <archivebox.core.widgets.URLFiltersWidget>`
  - ```{autodoc2-docstring} archivebox.core.widgets.URLFiltersWidget
    :summary:
    ```
* - {py:obj}`InlineTagEditorWidget <archivebox.core.widgets.InlineTagEditorWidget>`
  - ```{autodoc2-docstring} archivebox.core.widgets.InlineTagEditorWidget
    :summary:
    ```
````

### API

``````{py:class} TagEditorWidget(attrs=None, snapshot_id=None)
:canonical: archivebox.core.widgets.TagEditorWidget

Bases: {py:obj}`django.forms.Widget`

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget.__init__
```

````{py:attribute} template_name
:canonical: archivebox.core.widgets.TagEditorWidget.template_name
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget.template_name
```

````

`````{py:class} Media
:canonical: archivebox.core.widgets.TagEditorWidget.Media

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget.Media
```

````{py:attribute} css
:canonical: archivebox.core.widgets.TagEditorWidget.Media.css
:value: >
   None

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget.Media.css
```

````

````{py:attribute} js
:canonical: archivebox.core.widgets.TagEditorWidget.Media.js
:value: >
   []

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget.Media.js
```

````

`````

````{py:method} _escape(value)
:canonical: archivebox.core.widgets.TagEditorWidget._escape

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget._escape
```

````

````{py:method} _normalize_id(value)
:canonical: archivebox.core.widgets.TagEditorWidget._normalize_id

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget._normalize_id
```

````

````{py:method} _json_for_inline_script(value)
:canonical: archivebox.core.widgets.TagEditorWidget._json_for_inline_script

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget._json_for_inline_script
```

````

````{py:method} _tag_style(value)
:canonical: archivebox.core.widgets.TagEditorWidget._tag_style

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget._tag_style
```

````

````{py:method} render(name, value, attrs=None, renderer=None)
:canonical: archivebox.core.widgets.TagEditorWidget.render

```{autodoc2-docstring} archivebox.core.widgets.TagEditorWidget.render
```

````

``````

`````{py:class} URLFiltersWidget(attrs=None, *, source_selector='textarea[name="url"]')
:canonical: archivebox.core.widgets.URLFiltersWidget

Bases: {py:obj}`django.forms.Widget`

```{autodoc2-docstring} archivebox.core.widgets.URLFiltersWidget
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.widgets.URLFiltersWidget.__init__
```

````{py:attribute} template_name
:canonical: archivebox.core.widgets.URLFiltersWidget.template_name
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.core.widgets.URLFiltersWidget.template_name
```

````

````{py:method} render(name, value, attrs=None, renderer=None)
:canonical: archivebox.core.widgets.URLFiltersWidget.render

````

````{py:method} value_from_datadict(data, files, name)
:canonical: archivebox.core.widgets.URLFiltersWidget.value_from_datadict

````

`````

`````{py:class} InlineTagEditorWidget(attrs=None, snapshot_id=None, editable=True)
:canonical: archivebox.core.widgets.InlineTagEditorWidget

Bases: {py:obj}`archivebox.core.widgets.TagEditorWidget`

```{autodoc2-docstring} archivebox.core.widgets.InlineTagEditorWidget
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.widgets.InlineTagEditorWidget.__init__
```

````{py:method} render(name, value, attrs=None, renderer=None, snapshot_id=None)
:canonical: archivebox.core.widgets.InlineTagEditorWidget.render

```{autodoc2-docstring} archivebox.core.widgets.InlineTagEditorWidget.render
```

````

`````
