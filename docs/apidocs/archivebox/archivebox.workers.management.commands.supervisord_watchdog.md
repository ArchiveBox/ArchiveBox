# {py:mod}`archivebox.workers.management.commands.supervisord_watchdog`

```{py:module} archivebox.workers.management.commands.supervisord_watchdog
```

```{autodoc2-docstring} archivebox.workers.management.commands.supervisord_watchdog
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Command <archivebox.workers.management.commands.supervisord_watchdog.Command>`
  - ```{autodoc2-docstring} archivebox.workers.management.commands.supervisord_watchdog.Command
    :summary:
    ```
````

### API

`````{py:class} Command
:canonical: archivebox.workers.management.commands.supervisord_watchdog.Command

Bases: {py:obj}`django.core.management.base.BaseCommand`

```{autodoc2-docstring} archivebox.workers.management.commands.supervisord_watchdog.Command
```

````{py:attribute} help
:canonical: archivebox.workers.management.commands.supervisord_watchdog.Command.help
:value: >
   'Stop a foreground-owned supervisord if its exact ArchiveBox owner Process exits.'

```{autodoc2-docstring} archivebox.workers.management.commands.supervisord_watchdog.Command.help
```

````

````{py:method} add_arguments(parser)
:canonical: archivebox.workers.management.commands.supervisord_watchdog.Command.add_arguments

```{autodoc2-docstring} archivebox.workers.management.commands.supervisord_watchdog.Command.add_arguments
```

````

````{py:method} handle(*args, **kwargs)
:canonical: archivebox.workers.management.commands.supervisord_watchdog.Command.handle

```{autodoc2-docstring} archivebox.workers.management.commands.supervisord_watchdog.Command.handle
```

````

`````
