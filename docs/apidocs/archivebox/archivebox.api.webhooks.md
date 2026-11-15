# {py:mod}`archivebox.api.webhooks`

```{py:module} archivebox.api.webhooks
```

```{autodoc2-docstring} archivebox.api.webhooks
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`load_deferred_fields_for_delete_webhook <archivebox.api.webhooks.load_deferred_fields_for_delete_webhook>`
  - ```{autodoc2-docstring} archivebox.api.webhooks.load_deferred_fields_for_delete_webhook
    :summary:
    ```
* - {py:obj}`register_delete_webhook_field_loader <archivebox.api.webhooks.register_delete_webhook_field_loader>`
  - ```{autodoc2-docstring} archivebox.api.webhooks.register_delete_webhook_field_loader
    :summary:
    ```
* - {py:obj}`warning_error_handler <archivebox.api.webhooks.warning_error_handler>`
  - ```{autodoc2-docstring} archivebox.api.webhooks.warning_error_handler
    :summary:
    ```
* - {py:obj}`transaction_on_commit_task_handler <archivebox.api.webhooks.transaction_on_commit_task_handler>`
  - ```{autodoc2-docstring} archivebox.api.webhooks.transaction_on_commit_task_handler
    :summary:
    ```
* - {py:obj}`deliver_webhooks <archivebox.api.webhooks.deliver_webhooks>`
  - ```{autodoc2-docstring} archivebox.api.webhooks.deliver_webhooks
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`logger <archivebox.api.webhooks.logger>`
  - ```{autodoc2-docstring} archivebox.api.webhooks.logger
    :summary:
    ```
````

### API

````{py:data} logger
:canonical: archivebox.api.webhooks.logger
:value: >
   'getLogger(...)'

```{autodoc2-docstring} archivebox.api.webhooks.logger
```

````

````{py:function} load_deferred_fields_for_delete_webhook(sender, instance, using, **kwargs) -> None
:canonical: archivebox.api.webhooks.load_deferred_fields_for_delete_webhook

```{autodoc2-docstring} archivebox.api.webhooks.load_deferred_fields_for_delete_webhook
```
````

````{py:function} register_delete_webhook_field_loader() -> None
:canonical: archivebox.api.webhooks.register_delete_webhook_field_loader

```{autodoc2-docstring} archivebox.api.webhooks.register_delete_webhook_field_loader
```
````

````{py:function} warning_error_handler(hook: typing.Any, error: Exception | None) -> None
:canonical: archivebox.api.webhooks.warning_error_handler

```{autodoc2-docstring} archivebox.api.webhooks.warning_error_handler
```
````

````{py:function} transaction_on_commit_task_handler(hook: collections.abc.Callable[..., None], **kwargs: typing.Any) -> None
:canonical: archivebox.api.webhooks.transaction_on_commit_task_handler

```{autodoc2-docstring} archivebox.api.webhooks.transaction_on_commit_task_handler
```
````

````{py:function} deliver_webhooks(instance, data, method, *, metadata=None, subscriptions=None, payload=None)
:canonical: archivebox.api.webhooks.deliver_webhooks

```{autodoc2-docstring} archivebox.api.webhooks.deliver_webhooks
```
````
