# {py:mod}`archivebox.core.forms`

```{py:module} archivebox.core.forms
```

```{autodoc2-docstring} archivebox.core.forms
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`AddLinkForm <archivebox.core.forms.AddLinkForm>`
  -
* - {py:obj}`TagWidget <archivebox.core.forms.TagWidget>`
  -
* - {py:obj}`TagField <archivebox.core.forms.TagField>`
  - ```{autodoc2-docstring} archivebox.core.forms.TagField
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_split_strip <archivebox.core.forms._split_strip>`
  - ```{autodoc2-docstring} archivebox.core.forms._split_strip
    :summary:
    ```
* - {py:obj}`parse_tag_string <archivebox.core.forms.parse_tag_string>`
  - ```{autodoc2-docstring} archivebox.core.forms.parse_tag_string
    :summary:
    ```
* - {py:obj}`edit_string_for_tag_names <archivebox.core.forms.edit_string_for_tag_names>`
  - ```{autodoc2-docstring} archivebox.core.forms.edit_string_for_tag_names
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DEPTH_CHOICES <archivebox.core.forms.DEPTH_CHOICES>`
  - ```{autodoc2-docstring} archivebox.core.forms.DEPTH_CHOICES
    :summary:
    ```
````

### API

````{py:data} DEPTH_CHOICES
:canonical: archivebox.core.forms.DEPTH_CHOICES
:value: >
   (('0', 'depth = 0 (archive just these URLs)'), ('1', 'depth = 1 (+ URLs one hop away)'), ('2', 'dept...

```{autodoc2-docstring} archivebox.core.forms.DEPTH_CHOICES
```

````

````{py:function} _split_strip(value: str, delimiter: str) -> list[str]
:canonical: archivebox.core.forms._split_strip

```{autodoc2-docstring} archivebox.core.forms._split_strip
```
````

````{py:function} parse_tag_string(value: str | None) -> list[str]
:canonical: archivebox.core.forms.parse_tag_string

```{autodoc2-docstring} archivebox.core.forms.parse_tag_string
```
````

````{py:function} edit_string_for_tag_names(tags) -> str
:canonical: archivebox.core.forms.edit_string_for_tag_names

```{autodoc2-docstring} archivebox.core.forms.edit_string_for_tag_names
```
````

`````{py:class} AddLinkForm(*args, **kwargs)
:canonical: archivebox.core.forms.AddLinkForm

Bases: {py:obj}`archivebox.plugins.forms.PluginConfigFormMixin`, {py:obj}`django.forms.Form`

````{py:attribute} allow_crawl_execution_config_fields
:canonical: archivebox.core.forms.AddLinkForm.allow_crawl_execution_config_fields
:value: >
   False

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.allow_crawl_execution_config_fields
```

````

````{py:attribute} url
:canonical: archivebox.core.forms.AddLinkForm.url
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.url
```

````

````{py:attribute} tag
:canonical: archivebox.core.forms.AddLinkForm.tag
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.tag
```

````

````{py:attribute} depth
:canonical: archivebox.core.forms.AddLinkForm.depth
:value: >
   'ChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.depth
```

````

````{py:attribute} max_urls
:canonical: archivebox.core.forms.AddLinkForm.max_urls
:value: >
   'IntegerField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.max_urls
```

````

````{py:attribute} crawl_max_size
:canonical: archivebox.core.forms.AddLinkForm.crawl_max_size
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.crawl_max_size
```

````

````{py:attribute} crawl_timeout
:canonical: archivebox.core.forms.AddLinkForm.crawl_timeout
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.crawl_timeout
```

````

````{py:attribute} timeout
:canonical: archivebox.core.forms.AddLinkForm.timeout
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.timeout
```

````

````{py:attribute} snapshot_max_size
:canonical: archivebox.core.forms.AddLinkForm.snapshot_max_size
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.snapshot_max_size
```

````

````{py:attribute} delete_after
:canonical: archivebox.core.forms.AddLinkForm.delete_after
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.delete_after
```

````

````{py:attribute} crawl_max_concurrent_snapshots
:canonical: archivebox.core.forms.AddLinkForm.crawl_max_concurrent_snapshots
:value: >
   'IntegerField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.crawl_max_concurrent_snapshots
```

````

````{py:attribute} notes
:canonical: archivebox.core.forms.AddLinkForm.notes
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.notes
```

````

````{py:attribute} url_filters
:canonical: archivebox.core.forms.AddLinkForm.url_filters
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.url_filters
```

````

````{py:attribute} main_plugins
:canonical: archivebox.core.forms.AddLinkForm.main_plugins
:value: >
   'MultipleChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.main_plugins
```

````

````{py:attribute} page_setup_plugins
:canonical: archivebox.core.forms.AddLinkForm.page_setup_plugins
:value: >
   'MultipleChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.page_setup_plugins
```

````

````{py:attribute} media_plugins
:canonical: archivebox.core.forms.AddLinkForm.media_plugins
:value: >
   'MultipleChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.media_plugins
```

````

````{py:attribute} text_plugins
:canonical: archivebox.core.forms.AddLinkForm.text_plugins
:value: >
   'MultipleChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.text_plugins
```

````

````{py:attribute} metadata_plugins
:canonical: archivebox.core.forms.AddLinkForm.metadata_plugins
:value: >
   'MultipleChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.metadata_plugins
```

````

````{py:attribute} postprocessing_plugins
:canonical: archivebox.core.forms.AddLinkForm.postprocessing_plugins
:value: >
   'MultipleChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.postprocessing_plugins
```

````

````{py:attribute} other_plugins
:canonical: archivebox.core.forms.AddLinkForm.other_plugins
:value: >
   'MultipleChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.other_plugins
```

````

````{py:attribute} schedule
:canonical: archivebox.core.forms.AddLinkForm.schedule
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.schedule
```

````

````{py:attribute} persona
:canonical: archivebox.core.forms.AddLinkForm.persona
:value: >
   'ModelChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.persona
```

````

````{py:attribute} permissions
:canonical: archivebox.core.forms.AddLinkForm.permissions
:value: >
   'ChoiceField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.permissions
```

````

````{py:attribute} start_paused
:canonical: archivebox.core.forms.AddLinkForm.start_paused
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.start_paused
```

````

````{py:attribute} config
:canonical: archivebox.core.forms.AddLinkForm.config
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.config
```

````

````{py:method} clean()
:canonical: archivebox.core.forms.AddLinkForm.clean

````

````{py:method} clean_url()
:canonical: archivebox.core.forms.AddLinkForm.clean_url

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_url
```

````

````{py:method} clean_url_filters()
:canonical: archivebox.core.forms.AddLinkForm.clean_url_filters

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_url_filters
```

````

````{py:method} clean_max_urls()
:canonical: archivebox.core.forms.AddLinkForm.clean_max_urls

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_max_urls
```

````

````{py:method} clean_crawl_max_size()
:canonical: archivebox.core.forms.AddLinkForm.clean_crawl_max_size

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_crawl_max_size
```

````

````{py:method} clean_crawl_timeout()
:canonical: archivebox.core.forms.AddLinkForm.clean_crawl_timeout

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_crawl_timeout
```

````

````{py:method} clean_timeout()
:canonical: archivebox.core.forms.AddLinkForm.clean_timeout

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_timeout
```

````

````{py:method} _clean_timeout_seconds(raw_value, field_label: str, *, blank_value)
:canonical: archivebox.core.forms.AddLinkForm._clean_timeout_seconds

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm._clean_timeout_seconds
```

````

````{py:method} clean_snapshot_max_size()
:canonical: archivebox.core.forms.AddLinkForm.clean_snapshot_max_size

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_snapshot_max_size
```

````

````{py:method} clean_delete_after()
:canonical: archivebox.core.forms.AddLinkForm.clean_delete_after

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_delete_after
```

````

````{py:method} clean_crawl_max_concurrent_snapshots()
:canonical: archivebox.core.forms.AddLinkForm.clean_crawl_max_concurrent_snapshots

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_crawl_max_concurrent_snapshots
```

````

````{py:method} clean_schedule()
:canonical: archivebox.core.forms.AddLinkForm.clean_schedule

```{autodoc2-docstring} archivebox.core.forms.AddLinkForm.clean_schedule
```

````

`````

`````{py:class} TagWidget(attrs=None)
:canonical: archivebox.core.forms.TagWidget

Bases: {py:obj}`django.forms.TextInput`

````{py:method} format_value(value)
:canonical: archivebox.core.forms.TagWidget.format_value

````

`````

`````{py:class} TagField(*, max_length=None, min_length=None, strip=True, empty_value='', **kwargs)
:canonical: archivebox.core.forms.TagField

Bases: {py:obj}`django.forms.CharField`

```{autodoc2-docstring} archivebox.core.forms.TagField
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.forms.TagField.__init__
```

````{py:attribute} widget
:canonical: archivebox.core.forms.TagField.widget
:value: >
   None

```{autodoc2-docstring} archivebox.core.forms.TagField.widget
```

````

````{py:method} clean(value)
:canonical: archivebox.core.forms.TagField.clean

````

````{py:method} has_changed(initial, data)
:canonical: archivebox.core.forms.TagField.has_changed

````

`````
