# {py:mod}`archivebox.core.settings_logging`

```{py:module} archivebox.core.settings_logging
```

```{autodoc2-docstring} archivebox.core.settings_logging
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`NoisyRequestsFilter <archivebox.core.settings_logging.NoisyRequestsFilter>`
  -
* - {py:obj}`DaphneCloseTimeoutFilter <archivebox.core.settings_logging.DaphneCloseTimeoutFilter>`
  - ```{autodoc2-docstring} archivebox.core.settings_logging.DaphneCloseTimeoutFilter
    :summary:
    ```
* - {py:obj}`AsyncioCancelledShieldFilter <archivebox.core.settings_logging.AsyncioCancelledShieldFilter>`
  - ```{autodoc2-docstring} archivebox.core.settings_logging.AsyncioCancelledShieldFilter
    :summary:
    ```
* - {py:obj}`CustomOutboundWebhookLogFormatter <archivebox.core.settings_logging.CustomOutboundWebhookLogFormatter>`
  -
* - {py:obj}`StripANSIColorCodesFilter <archivebox.core.settings_logging.StripANSIColorCodesFilter>`
  -
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`IGNORABLE_URL_PATTERNS <archivebox.core.settings_logging.IGNORABLE_URL_PATTERNS>`
  - ```{autodoc2-docstring} archivebox.core.settings_logging.IGNORABLE_URL_PATTERNS
    :summary:
    ```
* - {py:obj}`ERROR_LOG <archivebox.core.settings_logging.ERROR_LOG>`
  - ```{autodoc2-docstring} archivebox.core.settings_logging.ERROR_LOG
    :summary:
    ```
* - {py:obj}`LOGS_DIR <archivebox.core.settings_logging.LOGS_DIR>`
  - ```{autodoc2-docstring} archivebox.core.settings_logging.LOGS_DIR
    :summary:
    ```
* - {py:obj}`LOG_LEVEL_DATABASE <archivebox.core.settings_logging.LOG_LEVEL_DATABASE>`
  - ```{autodoc2-docstring} archivebox.core.settings_logging.LOG_LEVEL_DATABASE
    :summary:
    ```
* - {py:obj}`LOG_LEVEL_REQUEST <archivebox.core.settings_logging.LOG_LEVEL_REQUEST>`
  - ```{autodoc2-docstring} archivebox.core.settings_logging.LOG_LEVEL_REQUEST
    :summary:
    ```
* - {py:obj}`SETTINGS_LOGGING <archivebox.core.settings_logging.SETTINGS_LOGGING>`
  - ```{autodoc2-docstring} archivebox.core.settings_logging.SETTINGS_LOGGING
    :summary:
    ```
````

### API

````{py:data} IGNORABLE_URL_PATTERNS
:canonical: archivebox.core.settings_logging.IGNORABLE_URL_PATTERNS
:value: >
   None

```{autodoc2-docstring} archivebox.core.settings_logging.IGNORABLE_URL_PATTERNS
```

````

`````{py:class} NoisyRequestsFilter(name='')
:canonical: archivebox.core.settings_logging.NoisyRequestsFilter

Bases: {py:obj}`logging.Filter`

````{py:method} filter(record) -> bool
:canonical: archivebox.core.settings_logging.NoisyRequestsFilter.filter

````

`````

`````{py:class} DaphneCloseTimeoutFilter(name='')
:canonical: archivebox.core.settings_logging.DaphneCloseTimeoutFilter

Bases: {py:obj}`logging.Filter`

```{autodoc2-docstring} archivebox.core.settings_logging.DaphneCloseTimeoutFilter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.settings_logging.DaphneCloseTimeoutFilter.__init__
```

````{py:method} filter(record) -> bool
:canonical: archivebox.core.settings_logging.DaphneCloseTimeoutFilter.filter

````

`````

`````{py:class} AsyncioCancelledShieldFilter(name='')
:canonical: archivebox.core.settings_logging.AsyncioCancelledShieldFilter

Bases: {py:obj}`logging.Filter`

```{autodoc2-docstring} archivebox.core.settings_logging.AsyncioCancelledShieldFilter
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.core.settings_logging.AsyncioCancelledShieldFilter.__init__
```

````{py:method} filter(record) -> bool
:canonical: archivebox.core.settings_logging.AsyncioCancelledShieldFilter.filter

````

`````

`````{py:class} CustomOutboundWebhookLogFormatter(fmt=None, datefmt=None, style='%', validate=True, *, defaults=None)
:canonical: archivebox.core.settings_logging.CustomOutboundWebhookLogFormatter

Bases: {py:obj}`logging.Formatter`

````{py:method} format(record)
:canonical: archivebox.core.settings_logging.CustomOutboundWebhookLogFormatter.format

````

`````

`````{py:class} StripANSIColorCodesFilter(name='')
:canonical: archivebox.core.settings_logging.StripANSIColorCodesFilter

Bases: {py:obj}`logging.Filter`

````{py:attribute} _ansi_re
:canonical: archivebox.core.settings_logging.StripANSIColorCodesFilter._ansi_re
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.core.settings_logging.StripANSIColorCodesFilter._ansi_re
```

````

````{py:attribute} _bare_re
:canonical: archivebox.core.settings_logging.StripANSIColorCodesFilter._bare_re
:value: >
   'compile(...)'

```{autodoc2-docstring} archivebox.core.settings_logging.StripANSIColorCodesFilter._bare_re
```

````

````{py:method} filter(record) -> bool
:canonical: archivebox.core.settings_logging.StripANSIColorCodesFilter.filter

````

`````

````{py:data} ERROR_LOG
:canonical: archivebox.core.settings_logging.ERROR_LOG
:value: >
   None

```{autodoc2-docstring} archivebox.core.settings_logging.ERROR_LOG
```

````

````{py:data} LOGS_DIR
:canonical: archivebox.core.settings_logging.LOGS_DIR
:value: >
   None

```{autodoc2-docstring} archivebox.core.settings_logging.LOGS_DIR
```

````

````{py:data} LOG_LEVEL_DATABASE
:canonical: archivebox.core.settings_logging.LOG_LEVEL_DATABASE
:value: >
   'WARNING'

```{autodoc2-docstring} archivebox.core.settings_logging.LOG_LEVEL_DATABASE
```

````

````{py:data} LOG_LEVEL_REQUEST
:canonical: archivebox.core.settings_logging.LOG_LEVEL_REQUEST
:value: >
   'WARNING'

```{autodoc2-docstring} archivebox.core.settings_logging.LOG_LEVEL_REQUEST
```

````

````{py:data} SETTINGS_LOGGING
:canonical: archivebox.core.settings_logging.SETTINGS_LOGGING
:value: >
   None

```{autodoc2-docstring} archivebox.core.settings_logging.SETTINGS_LOGGING
```

````
