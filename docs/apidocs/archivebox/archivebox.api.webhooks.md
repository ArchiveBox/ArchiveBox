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

* - {py:obj}`warning_error_handler <archivebox.api.webhooks.warning_error_handler>`
  - ```{autodoc2-docstring} archivebox.api.webhooks.warning_error_handler
    :summary:
    ```
* - {py:obj}`transaction_on_commit_task_handler <archivebox.api.webhooks.transaction_on_commit_task_handler>`
  - ```{autodoc2-docstring} archivebox.api.webhooks.transaction_on_commit_task_handler
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
