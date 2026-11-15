# {py:mod}`archivebox.base_models.admin`

```{py:module} archivebox.base_models.admin
```

```{autodoc2-docstring} archivebox.base_models.admin
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`HexUUIDConverter <archivebox.base_models.admin.HexUUIDConverter>`
  - ```{autodoc2-docstring} archivebox.base_models.admin.HexUUIDConverter
    :summary:
    ```
* - {py:obj}`ConfigOption <archivebox.base_models.admin.ConfigOption>`
  -
* - {py:obj}`KeyValueWidget <archivebox.base_models.admin.KeyValueWidget>`
  - ```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget
    :summary:
    ```
* - {py:obj}`ConfigEditorMixin <archivebox.base_models.admin.ConfigEditorMixin>`
  - ```{autodoc2-docstring} archivebox.base_models.admin.ConfigEditorMixin
    :summary:
    ```
* - {py:obj}`BaseModelAdmin <archivebox.base_models.admin.BaseModelAdmin>`
  - ```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin
    :summary:
    ```
````

### API

`````{py:class} HexUUIDConverter
:canonical: archivebox.base_models.admin.HexUUIDConverter

```{autodoc2-docstring} archivebox.base_models.admin.HexUUIDConverter
```

````{py:attribute} regex
:canonical: archivebox.base_models.admin.HexUUIDConverter.regex
:value: >
   '[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'

```{autodoc2-docstring} archivebox.base_models.admin.HexUUIDConverter.regex
```

````

````{py:method} to_python(value: str) -> str
:canonical: archivebox.base_models.admin.HexUUIDConverter.to_python

```{autodoc2-docstring} archivebox.base_models.admin.HexUUIDConverter.to_python
```

````

````{py:method} to_url(value) -> str
:canonical: archivebox.base_models.admin.HexUUIDConverter.to_url

```{autodoc2-docstring} archivebox.base_models.admin.HexUUIDConverter.to_url
```

````

`````

`````{py:class} ConfigOption()
:canonical: archivebox.base_models.admin.ConfigOption

Bases: {py:obj}`typing.TypedDict`

````{py:attribute} plugin
:canonical: archivebox.base_models.admin.ConfigOption.plugin
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.base_models.admin.ConfigOption.plugin
```

````

````{py:attribute} type
:canonical: archivebox.base_models.admin.ConfigOption.type
:type: str | list[str]
:value: >
   None

```{autodoc2-docstring} archivebox.base_models.admin.ConfigOption.type
```

````

````{py:attribute} default
:canonical: archivebox.base_models.admin.ConfigOption.default
:type: object
:value: >
   None

```{autodoc2-docstring} archivebox.base_models.admin.ConfigOption.default
```

````

````{py:attribute} description
:canonical: archivebox.base_models.admin.ConfigOption.description
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.base_models.admin.ConfigOption.description
```

````

````{py:attribute} enum
:canonical: archivebox.base_models.admin.ConfigOption.enum
:type: typing.NotRequired[list[object]]
:value: >
   None

```{autodoc2-docstring} archivebox.base_models.admin.ConfigOption.enum
```

````

````{py:attribute} pattern
:canonical: archivebox.base_models.admin.ConfigOption.pattern
:type: typing.NotRequired[str]
:value: >
   None

```{autodoc2-docstring} archivebox.base_models.admin.ConfigOption.pattern
```

````

````{py:attribute} minimum
:canonical: archivebox.base_models.admin.ConfigOption.minimum
:type: typing.NotRequired[int | float]
:value: >
   None

```{autodoc2-docstring} archivebox.base_models.admin.ConfigOption.minimum
```

````

````{py:attribute} maximum
:canonical: archivebox.base_models.admin.ConfigOption.maximum
:type: typing.NotRequired[int | float]
:value: >
   None

```{autodoc2-docstring} archivebox.base_models.admin.ConfigOption.maximum
```

````

`````

``````{py:class} KeyValueWidget
:canonical: archivebox.base_models.admin.KeyValueWidget

Bases: {py:obj}`django.forms.Widget`

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget
```

````{py:attribute} template_name
:canonical: archivebox.base_models.admin.KeyValueWidget.template_name
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget.template_name
```

````

`````{py:class} Media
:canonical: archivebox.base_models.admin.KeyValueWidget.Media

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget.Media
```

````{py:attribute} css
:canonical: archivebox.base_models.admin.KeyValueWidget.Media.css
:type: typing.ClassVar[dict[str, list[str]]]
:value: >
   None

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget.Media.css
```

````

````{py:attribute} js
:canonical: archivebox.base_models.admin.KeyValueWidget.Media.js
:type: typing.ClassVar[list[str]]
:value: >
   []

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget.Media.js
```

````

`````

````{py:method} _get_config_options() -> dict[str, archivebox.base_models.admin.ConfigOption]
:canonical: archivebox.base_models.admin.KeyValueWidget._get_config_options

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget._get_config_options
```

````

````{py:method} _parse_value(value: object) -> dict[str, object]
:canonical: archivebox.base_models.admin.KeyValueWidget._parse_value

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget._parse_value
```

````

````{py:method} render(name: str, value: object, attrs: collections.abc.Mapping[str, str] | None = None, renderer: django.forms.renderers.BaseRenderer | None = None) -> django.utils.safestring.SafeString
:canonical: archivebox.base_models.admin.KeyValueWidget.render

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget.render
```

````

````{py:method} _render_row(widget_id: str, key: str, value: str, original_json: str | None = None) -> str
:canonical: archivebox.base_models.admin.KeyValueWidget._render_row

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget._render_row
```

````

````{py:method} _escape(s: object) -> str
:canonical: archivebox.base_models.admin.KeyValueWidget._escape

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget._escape
```

````

````{py:method} value_from_datadict(data: django.http.QueryDict | collections.abc.Mapping[str, object], files: object, name: str) -> str
:canonical: archivebox.base_models.admin.KeyValueWidget.value_from_datadict

```{autodoc2-docstring} archivebox.base_models.admin.KeyValueWidget.value_from_datadict
```

````

``````

`````{py:class} ConfigEditorMixin
:canonical: archivebox.base_models.admin.ConfigEditorMixin

Bases: {py:obj}`django.contrib.admin.ModelAdmin`

```{autodoc2-docstring} archivebox.base_models.admin.ConfigEditorMixin
```

````{py:method} formfield_for_dbfield(db_field: django.db.models.Field, request: django.http.HttpRequest, **kwargs: object) -> django.forms.Field | None
:canonical: archivebox.base_models.admin.ConfigEditorMixin.formfield_for_dbfield

```{autodoc2-docstring} archivebox.base_models.admin.ConfigEditorMixin.formfield_for_dbfield
```

````

````{py:method} save_model(request: django.http.HttpRequest, obj, form, change)
:canonical: archivebox.base_models.admin.ConfigEditorMixin.save_model

```{autodoc2-docstring} archivebox.base_models.admin.ConfigEditorMixin.save_model
```

````

`````

`````{py:class} BaseModelAdmin
:canonical: archivebox.base_models.admin.BaseModelAdmin

Bases: {py:obj}`django_object_actions.DjangoObjectActions`, {py:obj}`django.contrib.admin.ModelAdmin`

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin
```

````{py:attribute} list_display
:canonical: archivebox.base_models.admin.BaseModelAdmin.list_display
:value: >
   ('id', 'created_at', 'created_by')

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin.list_display
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.base_models.admin.BaseModelAdmin.readonly_fields
:value: >
   ('id', 'created_at', 'modified_at')

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin.readonly_fields
```

````

````{py:attribute} show_search_mode_selector
:canonical: archivebox.base_models.admin.BaseModelAdmin.show_search_mode_selector
:value: >
   False

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin.show_search_mode_selector
```

````

````{py:attribute} change_form_template
:canonical: archivebox.base_models.admin.BaseModelAdmin.change_form_template
:value: >
   'admin/archivebox_change_form.html'

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin.change_form_template
```

````

````{py:method} get_admin_toolbar_actions(request, obj)
:canonical: archivebox.base_models.admin.BaseModelAdmin.get_admin_toolbar_actions

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin.get_admin_toolbar_actions
```

````

````{py:method} render_change_form(request, context, add=False, change=False, form_url='', obj=None)
:canonical: archivebox.base_models.admin.BaseModelAdmin.render_change_form

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin.render_change_form
```

````

````{py:method} get_default_search_mode() -> str
:canonical: archivebox.base_models.admin.BaseModelAdmin.get_default_search_mode

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin.get_default_search_mode
```

````

````{py:method} get_form(request: django.http.HttpRequest, obj: django.db.models.Model | None = None, change: bool = False, **kwargs: object)
:canonical: archivebox.base_models.admin.BaseModelAdmin.get_form

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin.get_form
```

````

````{py:method} get_urls()
:canonical: archivebox.base_models.admin.BaseModelAdmin.get_urls

```{autodoc2-docstring} archivebox.base_models.admin.BaseModelAdmin.get_urls
```

````

`````
