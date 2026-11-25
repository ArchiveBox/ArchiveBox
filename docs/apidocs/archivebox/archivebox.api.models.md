# {py:mod}`archivebox.api.models`

```{py:module} archivebox.api.models
```

```{autodoc2-docstring} archivebox.api.models
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`APIToken <archivebox.api.models.APIToken>`
  - ```{autodoc2-docstring} archivebox.api.models.APIToken
    :summary:
    ```
* - {py:obj}`Rule <archivebox.api.models.Rule>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`generate_secret_token <archivebox.api.models.generate_secret_token>`
  - ```{autodoc2-docstring} archivebox.api.models.generate_secret_token
    :summary:
    ```
````

### API

````{py:function} generate_secret_token() -> str
:canonical: archivebox.api.models.generate_secret_token

```{autodoc2-docstring} archivebox.api.models.generate_secret_token
```
````

``````{py:class} APIToken
:canonical: archivebox.api.models.APIToken

Bases: {py:obj}`django.db.models.Model`

```{autodoc2-docstring} archivebox.api.models.APIToken
```

````{py:attribute} emoji
:canonical: archivebox.api.models.APIToken.emoji
:type: str
:value: >
   '🔑'

```{autodoc2-docstring} archivebox.api.models.APIToken.emoji
```

````

````{py:attribute} id
:canonical: archivebox.api.models.APIToken.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.api.models.APIToken.id
```

````

````{py:attribute} created_by
:canonical: archivebox.api.models.APIToken.created_by
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.api.models.APIToken.created_by
```

````

````{py:attribute} created_at
:canonical: archivebox.api.models.APIToken.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.api.models.APIToken.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.models.APIToken.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.api.models.APIToken.modified_at
```

````

````{py:attribute} token
:canonical: archivebox.api.models.APIToken.token
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.api.models.APIToken.token
```

````

````{py:attribute} expires
:canonical: archivebox.api.models.APIToken.expires
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.api.models.APIToken.expires
```

````

`````{py:class} Meta
:canonical: archivebox.api.models.APIToken.Meta

Bases: {py:obj}`django_stubs_ext.db.models.TypedModelMeta`

```{autodoc2-docstring} archivebox.api.models.APIToken.Meta
```

````{py:attribute} app_label
:canonical: archivebox.api.models.APIToken.Meta.app_label
:value: >
   'api'

```{autodoc2-docstring} archivebox.api.models.APIToken.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.api.models.APIToken.Meta.verbose_name
:value: >
   'API Key'

```{autodoc2-docstring} archivebox.api.models.APIToken.Meta.verbose_name
```

````

````{py:attribute} verbose_name_plural
:canonical: archivebox.api.models.APIToken.Meta.verbose_name_plural
:value: >
   'API Keys'

```{autodoc2-docstring} archivebox.api.models.APIToken.Meta.verbose_name_plural
```

````

`````

````{py:method} __str__() -> str
:canonical: archivebox.api.models.APIToken.__str__

```{autodoc2-docstring} archivebox.api.models.APIToken.__str__
```

````

````{py:property} token_redacted
:canonical: archivebox.api.models.APIToken.token_redacted

```{autodoc2-docstring} archivebox.api.models.APIToken.token_redacted
```

````

````{py:method} is_valid(for_date=None)
:canonical: archivebox.api.models.APIToken.is_valid

```{autodoc2-docstring} archivebox.api.models.APIToken.is_valid
```

````

``````

``````{py:class} Rule
:canonical: archivebox.api.models.Rule

Bases: {py:obj}`signal_webhooks.models.WebhookBase`, {py:obj}`archivebox.base_models.models.ModelWithHealthStats`

````{py:attribute} emoji
:canonical: archivebox.api.models.Rule.emoji
:type: str
:value: >
   '🪝'

```{autodoc2-docstring} archivebox.api.models.Rule.emoji
```

````

````{py:attribute} id
:canonical: archivebox.api.models.Rule.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.id
```

````

````{py:attribute} created_by
:canonical: archivebox.api.models.Rule.created_by
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.created_by
```

````

````{py:attribute} created_at
:canonical: archivebox.api.models.Rule.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.models.Rule.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.modified_at
```

````

````{py:attribute} endpoint
:canonical: archivebox.api.models.Rule.endpoint
:value: >
   'URLField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.endpoint
```

````

````{py:attribute} last_success
:canonical: archivebox.api.models.Rule.last_success
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.last_success
```

````

````{py:attribute} last_failure
:canonical: archivebox.api.models.Rule.last_failure
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.last_failure
```

````

````{py:attribute} signal
:canonical: archivebox.api.models.Rule.signal
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.signal
```

````

````{py:attribute} actions
:canonical: archivebox.api.models.Rule.actions
:value: >
   'JSONField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.actions
```

````

````{py:attribute} folder
:canonical: archivebox.api.models.Rule.folder
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.folder
```

````

````{py:attribute} position
:canonical: archivebox.api.models.Rule.position
:value: >
   'PositiveIntegerField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.position
```

````

````{py:attribute} stop_processing
:canonical: archivebox.api.models.Rule.stop_processing
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.stop_processing
```

````

````{py:attribute} stop_on_failure
:canonical: archivebox.api.models.Rule.stop_on_failure
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.api.models.Rule.stop_on_failure
```

````

`````{py:class} Meta
:canonical: archivebox.api.models.Rule.Meta

Bases: {py:obj}`signal_webhooks.models.WebhookBase.Meta`

```{autodoc2-docstring} archivebox.api.models.Rule.Meta
```

````{py:attribute} app_label
:canonical: archivebox.api.models.Rule.Meta.app_label
:value: >
   'api'

```{autodoc2-docstring} archivebox.api.models.Rule.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.api.models.Rule.Meta.verbose_name
:value: >
   'Rule'

```{autodoc2-docstring} archivebox.api.models.Rule.Meta.verbose_name
```

````

````{py:attribute} ordering
:canonical: archivebox.api.models.Rule.Meta.ordering
:value: >
   ('position', 'created_at', 'pk')

```{autodoc2-docstring} archivebox.api.models.Rule.Meta.ordering
```

````

````{py:attribute} constraints
:canonical: archivebox.api.models.Rule.Meta.constraints
:value: >
   []

```{autodoc2-docstring} archivebox.api.models.Rule.Meta.constraints
```

````

`````

````{py:method} clean()
:canonical: archivebox.api.models.Rule.clean

```{autodoc2-docstring} archivebox.api.models.Rule.clean
```

````

````{py:method} __str__() -> str
:canonical: archivebox.api.models.Rule.__str__

```{autodoc2-docstring} archivebox.api.models.Rule.__str__
```

````

``````
