# {py:mod}`archivebox.api.webhook_events`

```{py:module} archivebox.api.webhook_events
```

```{autodoc2-docstring} archivebox.api.webhook_events
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`WebhookActionMiddleware <archivebox.api.webhook_events.WebhookActionMiddleware>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.WebhookActionMiddleware
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`action_in_progress <archivebox.api.webhook_events.action_in_progress>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.action_in_progress
    :summary:
    ```
* - {py:obj}`event_options <archivebox.api.webhook_events.event_options>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.event_options
    :summary:
    ```
* - {py:obj}`event_catalog <archivebox.api.webhook_events.event_catalog>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.event_catalog
    :summary:
    ```
* - {py:obj}`signal_choices <archivebox.api.webhook_events.signal_choices>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.signal_choices
    :summary:
    ```
* - {py:obj}`event_payload <archivebox.api.webhook_events.event_payload>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.event_payload
    :summary:
    ```
* - {py:obj}`track_lifecycle_update <archivebox.api.webhook_events.track_lifecycle_update>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.track_lifecycle_update
    :summary:
    ```
* - {py:obj}`emit_event <archivebox.api.webhook_events.emit_event>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.emit_event
    :summary:
    ```
* - {py:obj}`register_lifecycle_signals <archivebox.api.webhook_events.register_lifecycle_signals>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.register_lifecycle_signals
    :summary:
    ```
* - {py:obj}`track_model_update <archivebox.api.webhook_events.track_model_update>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.track_model_update
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`executing_webhook <archivebox.api.webhook_events.executing_webhook>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.executing_webhook
    :summary:
    ```
* - {py:obj}`EVENTS <archivebox.api.webhook_events.EVENTS>`
  - ```{autodoc2-docstring} archivebox.api.webhook_events.EVENTS
    :summary:
    ```
````

### API

````{py:data} executing_webhook
:canonical: archivebox.api.webhook_events.executing_webhook
:value: >
   'ContextVar(...)'

```{autodoc2-docstring} archivebox.api.webhook_events.executing_webhook
```

````

````{py:function} action_in_progress()
:canonical: archivebox.api.webhook_events.action_in_progress

```{autodoc2-docstring} archivebox.api.webhook_events.action_in_progress
```
````

`````{py:class} WebhookActionMiddleware(get_response)
:canonical: archivebox.api.webhook_events.WebhookActionMiddleware

```{autodoc2-docstring} archivebox.api.webhook_events.WebhookActionMiddleware
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.api.webhook_events.WebhookActionMiddleware.__init__
```

````{py:method} __call__(request)
:canonical: archivebox.api.webhook_events.WebhookActionMiddleware.__call__

```{autodoc2-docstring} archivebox.api.webhook_events.WebhookActionMiddleware.__call__
```

````

`````

````{py:data} EVENTS
:canonical: archivebox.api.webhook_events.EVENTS
:value: >
   None

```{autodoc2-docstring} archivebox.api.webhook_events.EVENTS
```

````

````{py:function} event_options(model, event)
:canonical: archivebox.api.webhook_events.event_options

```{autodoc2-docstring} archivebox.api.webhook_events.event_options
```
````

````{py:function} event_catalog()
:canonical: archivebox.api.webhook_events.event_catalog

```{autodoc2-docstring} archivebox.api.webhook_events.event_catalog
```
````

````{py:function} signal_choices()
:canonical: archivebox.api.webhook_events.signal_choices

```{autodoc2-docstring} archivebox.api.webhook_events.signal_choices
```
````

````{py:function} event_payload(instance, signal, *, data=None, **metadata)
:canonical: archivebox.api.webhook_events.event_payload

```{autodoc2-docstring} archivebox.api.webhook_events.event_payload
```
````

````{py:function} track_lifecycle_update(queryset, fields)
:canonical: archivebox.api.webhook_events.track_lifecycle_update

```{autodoc2-docstring} archivebox.api.webhook_events.track_lifecycle_update
```
````

````{py:function} emit_event(instance, signal, **metadata)
:canonical: archivebox.api.webhook_events.emit_event

```{autodoc2-docstring} archivebox.api.webhook_events.emit_event
```
````

````{py:function} register_lifecycle_signals()
:canonical: archivebox.api.webhook_events.register_lifecycle_signals

```{autodoc2-docstring} archivebox.api.webhook_events.register_lifecycle_signals
```
````

````{py:function} track_model_update(queryset, fields)
:canonical: archivebox.api.webhook_events.track_model_update

```{autodoc2-docstring} archivebox.api.webhook_events.track_model_update
```
````
