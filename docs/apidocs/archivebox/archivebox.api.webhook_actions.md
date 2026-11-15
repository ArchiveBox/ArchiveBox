# {py:mod}`archivebox.api.webhook_actions`

```{py:module} archivebox.api.webhook_actions
```

```{autodoc2-docstring} archivebox.api.webhook_actions
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`configurable_fields <archivebox.api.webhook_actions.configurable_fields>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions.configurable_fields
    :summary:
    ```
* - {py:obj}`validate_actions <archivebox.api.webhook_actions.validate_actions>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions.validate_actions
    :summary:
    ```
* - {py:obj}`_render <archivebox.api.webhook_actions._render>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions._render
    :summary:
    ```
* - {py:obj}`_apply_capture_action <archivebox.api.webhook_actions._apply_capture_action>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions._apply_capture_action
    :summary:
    ```
* - {py:obj}`_apply_model_action <archivebox.api.webhook_actions._apply_model_action>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions._apply_model_action
    :summary:
    ```
* - {py:obj}`_request <archivebox.api.webhook_actions._request>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions._request
    :summary:
    ```
* - {py:obj}`execute_actions <archivebox.api.webhook_actions.execute_actions>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions.execute_actions
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`logger <archivebox.api.webhook_actions.logger>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions.logger
    :summary:
    ```
* - {py:obj}`ACTION_FIELDS <archivebox.api.webhook_actions.ACTION_FIELDS>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions.ACTION_FIELDS
    :summary:
    ```
* - {py:obj}`CAPTURE_ACTIONS <archivebox.api.webhook_actions.CAPTURE_ACTIONS>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions.CAPTURE_ACTIONS
    :summary:
    ```
* - {py:obj}`SNAPSHOT_ACTIONS <archivebox.api.webhook_actions.SNAPSHOT_ACTIONS>`
  - ```{autodoc2-docstring} archivebox.api.webhook_actions.SNAPSHOT_ACTIONS
    :summary:
    ```
````

### API

````{py:data} logger
:canonical: archivebox.api.webhook_actions.logger
:value: >
   'getLogger(...)'

```{autodoc2-docstring} archivebox.api.webhook_actions.logger
```

````

````{py:data} ACTION_FIELDS
:canonical: archivebox.api.webhook_actions.ACTION_FIELDS
:value: >
   None

```{autodoc2-docstring} archivebox.api.webhook_actions.ACTION_FIELDS
```

````

````{py:data} CAPTURE_ACTIONS
:canonical: archivebox.api.webhook_actions.CAPTURE_ACTIONS
:value: >
   None

```{autodoc2-docstring} archivebox.api.webhook_actions.CAPTURE_ACTIONS
```

````

````{py:data} SNAPSHOT_ACTIONS
:canonical: archivebox.api.webhook_actions.SNAPSHOT_ACTIONS
:value: >
   None

```{autodoc2-docstring} archivebox.api.webhook_actions.SNAPSHOT_ACTIONS
```

````

````{py:function} configurable_fields()
:canonical: archivebox.api.webhook_actions.configurable_fields

```{autodoc2-docstring} archivebox.api.webhook_actions.configurable_fields
```
````

````{py:function} validate_actions(hook)
:canonical: archivebox.api.webhook_actions.validate_actions

```{autodoc2-docstring} archivebox.api.webhook_actions.validate_actions
```
````

````{py:function} _render(value, payload)
:canonical: archivebox.api.webhook_actions._render

```{autodoc2-docstring} archivebox.api.webhook_actions._render
```
````

````{py:function} _apply_capture_action(action, instance)
:canonical: archivebox.api.webhook_actions._apply_capture_action

```{autodoc2-docstring} archivebox.api.webhook_actions._apply_capture_action
```
````

````{py:function} _apply_model_action(action, instance, hook)
:canonical: archivebox.api.webhook_actions._apply_model_action

```{autodoc2-docstring} archivebox.api.webhook_actions._apply_model_action
```
````

````{py:function} _request(action, hook, payload)
:canonical: archivebox.api.webhook_actions._request

```{autodoc2-docstring} archivebox.api.webhook_actions._request
```
````

````{py:function} execute_actions(hook, instance, signal, payload) -> bool
:canonical: archivebox.api.webhook_actions.execute_actions

```{autodoc2-docstring} archivebox.api.webhook_actions.execute_actions
```
````
