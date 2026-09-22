# {py:mod}`archivebox.api.admin`

```{py:module} archivebox.api.admin
```

```{autodoc2-docstring} archivebox.api.admin
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`APITokenAdmin <archivebox.api.admin.APITokenAdmin>`
  -
* - {py:obj}`OutboundWebhookAdminForm <archivebox.api.admin.OutboundWebhookAdminForm>`
  -
* - {py:obj}`CustomWebhookAdmin <archivebox.api.admin.CustomWebhookAdmin>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_webhook_fields <archivebox.api.admin._webhook_fields>`
  - ```{autodoc2-docstring} archivebox.api.admin._webhook_fields
    :summary:
    ```
* - {py:obj}`register_admin <archivebox.api.admin.register_admin>`
  - ```{autodoc2-docstring} archivebox.api.admin.register_admin
    :summary:
    ```
````

### API

````{py:function} _webhook_fields(*names: str) -> tuple[str, ...]
:canonical: archivebox.api.admin._webhook_fields

```{autodoc2-docstring} archivebox.api.admin._webhook_fields
```
````

`````{py:class} APITokenAdmin(model, admin_site)
:canonical: archivebox.api.admin.APITokenAdmin

Bases: {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} list_display
:canonical: archivebox.api.admin.APITokenAdmin.list_display
:value: >
   ('created_at', 'id', 'created_by', 'token_redacted', 'expires')

```{autodoc2-docstring} archivebox.api.admin.APITokenAdmin.list_display
```

````

````{py:attribute} sort_fields
:canonical: archivebox.api.admin.APITokenAdmin.sort_fields
:value: >
   ('id', 'created_at', 'created_by', 'expires')

```{autodoc2-docstring} archivebox.api.admin.APITokenAdmin.sort_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.api.admin.APITokenAdmin.readonly_fields
:value: >
   ('created_at', 'modified_at')

```{autodoc2-docstring} archivebox.api.admin.APITokenAdmin.readonly_fields
```

````

````{py:attribute} search_fields
:canonical: archivebox.api.admin.APITokenAdmin.search_fields
:value: >
   ('id', 'created_by__username', 'token')

```{autodoc2-docstring} archivebox.api.admin.APITokenAdmin.search_fields
```

````

````{py:attribute} fieldsets
:canonical: archivebox.api.admin.APITokenAdmin.fieldsets
:value: >
   (('Token',), ('Owner',), ('Timestamps',))

```{autodoc2-docstring} archivebox.api.admin.APITokenAdmin.fieldsets
```

````

````{py:attribute} list_filter
:canonical: archivebox.api.admin.APITokenAdmin.list_filter
:value: >
   ('created_by',)

```{autodoc2-docstring} archivebox.api.admin.APITokenAdmin.list_filter
```

````

````{py:attribute} ordering
:canonical: archivebox.api.admin.APITokenAdmin.ordering
:value: >
   ['-created_at']

```{autodoc2-docstring} archivebox.api.admin.APITokenAdmin.ordering
```

````

````{py:attribute} list_per_page
:canonical: archivebox.api.admin.APITokenAdmin.list_per_page
:value: >
   100

```{autodoc2-docstring} archivebox.api.admin.APITokenAdmin.list_per_page
```

````

`````

```{py:class} OutboundWebhookAdminForm(*args, **kwargs)
:canonical: archivebox.api.admin.OutboundWebhookAdminForm

Bases: {py:obj}`signal_webhooks.admin.WebhookModelForm`

```

`````{py:class} CustomWebhookAdmin(model, admin_site)
:canonical: archivebox.api.admin.CustomWebhookAdmin

Bases: {py:obj}`signal_webhooks.admin.WebhookAdmin`, {py:obj}`archivebox.base_models.admin.BaseModelAdmin`

````{py:attribute} form
:canonical: archivebox.api.admin.CustomWebhookAdmin.form
:value: >
   None

```{autodoc2-docstring} archivebox.api.admin.CustomWebhookAdmin.form
```

````

````{py:attribute} list_display
:canonical: archivebox.api.admin.CustomWebhookAdmin.list_display
:value: >
   ('created_at', 'created_by', 'id')

```{autodoc2-docstring} archivebox.api.admin.CustomWebhookAdmin.list_display
```

````

````{py:attribute} sort_fields
:canonical: archivebox.api.admin.CustomWebhookAdmin.sort_fields
:value: >
   '_webhook_fields(...)'

```{autodoc2-docstring} archivebox.api.admin.CustomWebhookAdmin.sort_fields
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.api.admin.CustomWebhookAdmin.readonly_fields
:value: >
   '_webhook_fields(...)'

```{autodoc2-docstring} archivebox.api.admin.CustomWebhookAdmin.readonly_fields
```

````

````{py:attribute} fieldsets
:canonical: archivebox.api.admin.CustomWebhookAdmin.fieldsets
:value: >
   (('Webhook',), ('Authentication',), ('Status',), ('Owner',), ('Timestamps',))

```{autodoc2-docstring} archivebox.api.admin.CustomWebhookAdmin.fieldsets
```

````

````{py:method} lookup_allowed(lookup: str, value: str, request: django.http.HttpRequest | None = None) -> bool
:canonical: archivebox.api.admin.CustomWebhookAdmin.lookup_allowed

```{autodoc2-docstring} archivebox.api.admin.CustomWebhookAdmin.lookup_allowed
```

````

`````

````{py:function} register_admin(admin_site: django.contrib.admin.AdminSite) -> None
:canonical: archivebox.api.admin.register_admin

```{autodoc2-docstring} archivebox.api.admin.register_admin
```
````
