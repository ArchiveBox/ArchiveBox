# {py:mod}`archivebox.importers.management.commands.importers`

```{py:module} archivebox.importers.management.commands.importers
```

```{autodoc2-docstring} archivebox.importers.management.commands.importers
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Command <archivebox.importers.management.commands.importers.Command>`
  - ```{autodoc2-docstring} archivebox.importers.management.commands.importers.Command
    :summary:
    ```
````

### API

`````{py:class} Command
:canonical: archivebox.importers.management.commands.importers.Command

Bases: {py:obj}`django.core.management.base.BaseCommand`

```{autodoc2-docstring} archivebox.importers.management.commands.importers.Command
```

````{py:attribute} help
:canonical: archivebox.importers.management.commands.importers.Command.help
:value: >
   'Run queued plugin importers, or enqueue an action for a configured source.'

```{autodoc2-docstring} archivebox.importers.management.commands.importers.Command.help
```

````

````{py:method} add_arguments(parser)
:canonical: archivebox.importers.management.commands.importers.Command.add_arguments

```{autodoc2-docstring} archivebox.importers.management.commands.importers.Command.add_arguments
```

````

````{py:method} handle(*args, **options)
:canonical: archivebox.importers.management.commands.importers.Command.handle

```{autodoc2-docstring} archivebox.importers.management.commands.importers.Command.handle
```

````

`````
