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
  -
* - {py:obj}`OutboundWebhook <archivebox.api.models.OutboundWebhook>`
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

``````{py:class} APIToken(*args, **kwargs)
:canonical: archivebox.api.models.APIToken

Bases: {py:obj}`django.db.models.Model`

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

``````{py:class} OutboundWebhook(*args, **kwargs)
:canonical: archivebox.api.models.OutboundWebhook

Bases: {py:obj}`signal_webhooks.models.WebhookBase`

````{py:attribute} id
:canonical: archivebox.api.models.OutboundWebhook.id
:value: >
   'CompactUUIDField(...)'

```{autodoc2-docstring} archivebox.api.models.OutboundWebhook.id
```

````

````{py:attribute} created_by
:canonical: archivebox.api.models.OutboundWebhook.created_by
:value: >
   'ForeignKey(...)'

```{autodoc2-docstring} archivebox.api.models.OutboundWebhook.created_by
```

````

````{py:attribute} created_at
:canonical: archivebox.api.models.OutboundWebhook.created_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.api.models.OutboundWebhook.created_at
```

````

````{py:attribute} modified_at
:canonical: archivebox.api.models.OutboundWebhook.modified_at
:value: >
   'DateTimeField(...)'

```{autodoc2-docstring} archivebox.api.models.OutboundWebhook.modified_at
```

````

`````{py:class} Meta
:canonical: archivebox.api.models.OutboundWebhook.Meta

Bases: {py:obj}`signal_webhooks.models.WebhookBase.Meta`

```{autodoc2-docstring} archivebox.api.models.OutboundWebhook.Meta
```

````{py:attribute} app_label
:canonical: archivebox.api.models.OutboundWebhook.Meta.app_label
:value: >
   'api'

```{autodoc2-docstring} archivebox.api.models.OutboundWebhook.Meta.app_label
```

````

````{py:attribute} verbose_name
:canonical: archivebox.api.models.OutboundWebhook.Meta.verbose_name
:value: >
   'API Outbound Webhook'

```{autodoc2-docstring} archivebox.api.models.OutboundWebhook.Meta.verbose_name
```

````

`````

````{py:method} __str__() -> str
:canonical: archivebox.api.models.OutboundWebhook.__str__

````

``````
