# {py:mod}`archivebox.cli.archivebox_importer`

```{py:module} archivebox.cli.archivebox_importer
```

```{autodoc2-docstring} archivebox.cli.archivebox_importer
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`main <archivebox.cli.archivebox_importer.main>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.main
    :summary:
    ```
* - {py:obj}`catalog <archivebox.cli.archivebox_importer.catalog>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.catalog
    :summary:
    ```
* - {py:obj}`list_sources <archivebox.cli.archivebox_importer.list_sources>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.list_sources
    :summary:
    ```
* - {py:obj}`get_source <archivebox.cli.archivebox_importer.get_source>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.get_source
    :summary:
    ```
* - {py:obj}`create_source <archivebox.cli.archivebox_importer.create_source>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.create_source
    :summary:
    ```
* - {py:obj}`update_source <archivebox.cli.archivebox_importer.update_source>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.update_source
    :summary:
    ```
* - {py:obj}`delete_source <archivebox.cli.archivebox_importer.delete_source>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.delete_source
    :summary:
    ```
* - {py:obj}`source_action <archivebox.cli.archivebox_importer.source_action>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.source_action
    :summary:
    ```
* - {py:obj}`list_runs <archivebox.cli.archivebox_importer.list_runs>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.list_runs
    :summary:
    ```
* - {py:obj}`get_run <archivebox.cli.archivebox_importer.get_run>`
  - ```{autodoc2-docstring} archivebox.cli.archivebox_importer.get_run
    :summary:
    ```
````

### API

````{py:function} main()
:canonical: archivebox.cli.archivebox_importer.main

```{autodoc2-docstring} archivebox.cli.archivebox_importer.main
```
````

````{py:function} catalog()
:canonical: archivebox.cli.archivebox_importer.catalog

```{autodoc2-docstring} archivebox.cli.archivebox_importer.catalog
```
````

````{py:function} list_sources(format)
:canonical: archivebox.cli.archivebox_importer.list_sources

```{autodoc2-docstring} archivebox.cli.archivebox_importer.list_sources
```
````

````{py:function} get_source(source_id)
:canonical: archivebox.cli.archivebox_importer.get_source

```{autodoc2-docstring} archivebox.cli.archivebox_importer.get_source
```
````

````{py:function} create_source(plugin, feed, name, settings, persona_id, folder_id, schedule, tags, limit)
:canonical: archivebox.cli.archivebox_importer.create_source

```{autodoc2-docstring} archivebox.cli.archivebox_importer.create_source
```
````

````{py:function} update_source(source_id, data)
:canonical: archivebox.cli.archivebox_importer.update_source

```{autodoc2-docstring} archivebox.cli.archivebox_importer.update_source
```
````

````{py:function} delete_source(source_id, yes)
:canonical: archivebox.cli.archivebox_importer.delete_source

```{autodoc2-docstring} archivebox.cli.archivebox_importer.delete_source
```
````

````{py:function} source_action(source_id, operation)
:canonical: archivebox.cli.archivebox_importer.source_action

```{autodoc2-docstring} archivebox.cli.archivebox_importer.source_action
```
````

````{py:function} list_runs(source_id, limit, offset, format)
:canonical: archivebox.cli.archivebox_importer.list_runs

```{autodoc2-docstring} archivebox.cli.archivebox_importer.list_runs
```
````

````{py:function} get_run(run_id)
:canonical: archivebox.cli.archivebox_importer.get_run

```{autodoc2-docstring} archivebox.cli.archivebox_importer.get_run
```
````
