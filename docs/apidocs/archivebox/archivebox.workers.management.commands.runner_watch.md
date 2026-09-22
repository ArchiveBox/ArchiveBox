# {py:mod}`archivebox.workers.management.commands.runner_watch`

```{py:module} archivebox.workers.management.commands.runner_watch
```

```{autodoc2-docstring} archivebox.workers.management.commands.runner_watch
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Command <archivebox.workers.management.commands.runner_watch.Command>`
  -
````

### API

`````{py:class} Command(stdout=None, stderr=None, no_color=False, force_color=False)
:canonical: archivebox.workers.management.commands.runner_watch.Command

Bases: {py:obj}`django.core.management.base.BaseCommand`

````{py:attribute} help
:canonical: archivebox.workers.management.commands.runner_watch.Command.help
:value: >
   'Watch the debug runserver Process row and restart the background runner on autoreloads.'

```{autodoc2-docstring} archivebox.workers.management.commands.runner_watch.Command.help
```

````

````{py:method} add_arguments(parser)
:canonical: archivebox.workers.management.commands.runner_watch.Command.add_arguments

````

````{py:method} handle(*args, **kwargs)
:canonical: archivebox.workers.management.commands.runner_watch.Command.handle

````

`````
