# {py:mod}`archivebox.importers.diagnostics`

```{py:module} archivebox.importers.diagnostics
```

```{autodoc2-docstring} archivebox.importers.diagnostics
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`run_directory <archivebox.importers.diagnostics.run_directory>`
  - ```{autodoc2-docstring} archivebox.importers.diagnostics.run_directory
    :summary:
    ```
* - {py:obj}`artifact_path <archivebox.importers.diagnostics.artifact_path>`
  - ```{autodoc2-docstring} archivebox.importers.diagnostics.artifact_path
    :summary:
    ```
* - {py:obj}`_read <archivebox.importers.diagnostics._read>`
  - ```{autodoc2-docstring} archivebox.importers.diagnostics._read
    :summary:
    ```
* - {py:obj}`diagnostics <archivebox.importers.diagnostics.diagnostics>`
  - ```{autodoc2-docstring} archivebox.importers.diagnostics.diagnostics
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOG_NAME <archivebox.importers.diagnostics.LOG_NAME>`
  - ```{autodoc2-docstring} archivebox.importers.diagnostics.LOG_NAME
    :summary:
    ```
* - {py:obj}`SCREENSHOT_NAME <archivebox.importers.diagnostics.SCREENSHOT_NAME>`
  - ```{autodoc2-docstring} archivebox.importers.diagnostics.SCREENSHOT_NAME
    :summary:
    ```
* - {py:obj}`WINDOW <archivebox.importers.diagnostics.WINDOW>`
  - ```{autodoc2-docstring} archivebox.importers.diagnostics.WINDOW
    :summary:
    ```
````

### API

````{py:data} LOG_NAME
:canonical: archivebox.importers.diagnostics.LOG_NAME
:value: >
   '(?:learning-\\d+\\.jsonl|replay-\\d+\\.log|harness\\.log|failure\\.log|command-error\\.log|evidence\\.log)'

```{autodoc2-docstring} archivebox.importers.diagnostics.LOG_NAME
```

````

````{py:data} SCREENSHOT_NAME
:canonical: archivebox.importers.diagnostics.SCREENSHOT_NAME
:value: >
   'failure-[0-2]\\.png'

```{autodoc2-docstring} archivebox.importers.diagnostics.SCREENSHOT_NAME
```

````

````{py:data} WINDOW
:canonical: archivebox.importers.diagnostics.WINDOW
:value: >
   None

```{autodoc2-docstring} archivebox.importers.diagnostics.WINDOW
```

````

````{py:function} run_directory(run)
:canonical: archivebox.importers.diagnostics.run_directory

```{autodoc2-docstring} archivebox.importers.diagnostics.run_directory
```
````

````{py:function} artifact_path(run, name, pattern)
:canonical: archivebox.importers.diagnostics.artifact_path

```{autodoc2-docstring} archivebox.importers.diagnostics.artifact_path
```
````

````{py:function} _read(directory, files)
:canonical: archivebox.importers.diagnostics._read

```{autodoc2-docstring} archivebox.importers.diagnostics._read
```
````

````{py:function} diagnostics(run)
:canonical: archivebox.importers.diagnostics.diagnostics

```{autodoc2-docstring} archivebox.importers.diagnostics.diagnostics
```
````
