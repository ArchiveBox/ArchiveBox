# {py:mod}`archivebox.misc.logging_util`

```{py:module} archivebox.misc.logging_util
```

```{autodoc2-docstring} archivebox.misc.logging_util
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TimedProgress <archivebox.misc.logging_util.TimedProgress>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.TimedProgress
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`progress_bar <archivebox.misc.logging_util.progress_bar>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.progress_bar
    :summary:
    ```
* - {py:obj}`log_cli_command <archivebox.misc.logging_util.log_cli_command>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.log_cli_command
    :summary:
    ```
* - {py:obj}`log_list_started <archivebox.misc.logging_util.log_list_started>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.log_list_started
    :summary:
    ```
* - {py:obj}`log_list_finished <archivebox.misc.logging_util.log_list_finished>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.log_list_finished
    :summary:
    ```
* - {py:obj}`log_removal_started <archivebox.misc.logging_util.log_removal_started>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.log_removal_started
    :summary:
    ```
* - {py:obj}`log_removal_finished <archivebox.misc.logging_util.log_removal_finished>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.log_removal_finished
    :summary:
    ```
* - {py:obj}`pretty_path <archivebox.misc.logging_util.pretty_path>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.pretty_path
    :summary:
    ```
* - {py:obj}`printable_filesize <archivebox.misc.logging_util.printable_filesize>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.printable_filesize
    :summary:
    ```
* - {py:obj}`format_duration <archivebox.misc.logging_util.format_duration>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.format_duration
    :summary:
    ```
* - {py:obj}`truncate_url <archivebox.misc.logging_util.truncate_url>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.truncate_url
    :summary:
    ```
* - {py:obj}`log_worker_event <archivebox.misc.logging_util.log_worker_event>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.log_worker_event
    :summary:
    ```
* - {py:obj}`printable_folders <archivebox.misc.logging_util.printable_folders>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.printable_folders
    :summary:
    ```
* - {py:obj}`printable_config <archivebox.misc.logging_util.printable_config>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.printable_config
    :summary:
    ```
* - {py:obj}`printable_folder_status <archivebox.misc.logging_util.printable_folder_status>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.printable_folder_status
    :summary:
    ```
* - {py:obj}`printable_dependency_version <archivebox.misc.logging_util.printable_dependency_version>`
  - ```{autodoc2-docstring} archivebox.misc.logging_util.printable_dependency_version
    :summary:
    ```
````

### API

`````{py:class} TimedProgress(seconds, prefix='', config=None, **config_kwargs)
:canonical: archivebox.misc.logging_util.TimedProgress

```{autodoc2-docstring} archivebox.misc.logging_util.TimedProgress
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.misc.logging_util.TimedProgress.__init__
```

````{py:method} end()
:canonical: archivebox.misc.logging_util.TimedProgress.end

```{autodoc2-docstring} archivebox.misc.logging_util.TimedProgress.end
```

````

`````

````{py:function} progress_bar(seconds: int, prefix: str = '', ANSI: dict[str, str] = ANSI, config=None, **config_kwargs) -> None
:canonical: archivebox.misc.logging_util.progress_bar

```{autodoc2-docstring} archivebox.misc.logging_util.progress_bar
```
````

````{py:function} log_cli_command(subcommand: str, subcommand_args: collections.abc.Iterable[str] = (), stdin: str | typing.IO | None = None, pwd: str = '.')
:canonical: archivebox.misc.logging_util.log_cli_command

```{autodoc2-docstring} archivebox.misc.logging_util.log_cli_command
```
````

````{py:function} log_list_started(filter_patterns: list[str] | None, filter_type: str)
:canonical: archivebox.misc.logging_util.log_list_started

```{autodoc2-docstring} archivebox.misc.logging_util.log_list_started
```
````

````{py:function} log_list_finished(snapshots)
:canonical: archivebox.misc.logging_util.log_list_finished

```{autodoc2-docstring} archivebox.misc.logging_util.log_list_finished
```
````

````{py:function} log_removal_started(snapshots, yes: bool)
:canonical: archivebox.misc.logging_util.log_removal_started

```{autodoc2-docstring} archivebox.misc.logging_util.log_removal_started
```
````

````{py:function} log_removal_finished(remaining_links: int, removed_links: int)
:canonical: archivebox.misc.logging_util.log_removal_finished

```{autodoc2-docstring} archivebox.misc.logging_util.log_removal_finished
```
````

````{py:function} pretty_path(path: pathlib.Path | str, pwd: pathlib.Path | str = CONSTANTS.DATA_DIR, color: bool = True) -> str
:canonical: archivebox.misc.logging_util.pretty_path

```{autodoc2-docstring} archivebox.misc.logging_util.pretty_path
```
````

````{py:function} printable_filesize(num_bytes: int | float) -> str
:canonical: archivebox.misc.logging_util.printable_filesize

```{autodoc2-docstring} archivebox.misc.logging_util.printable_filesize
```
````

````{py:function} format_duration(seconds: float) -> str
:canonical: archivebox.misc.logging_util.format_duration

```{autodoc2-docstring} archivebox.misc.logging_util.format_duration
```
````

````{py:function} truncate_url(url: str, max_length: int = 60) -> str
:canonical: archivebox.misc.logging_util.truncate_url

```{autodoc2-docstring} archivebox.misc.logging_util.truncate_url
```
````

````{py:function} log_worker_event(worker_type: str, event: str, indent_level: int = 0, pid: int | None = None, worker_id: str | None = None, url: str | None = None, plugin: str | None = None, metadata: dict[str, typing.Any] | None = None, error: Exception | None = None) -> None
:canonical: archivebox.misc.logging_util.log_worker_event

```{autodoc2-docstring} archivebox.misc.logging_util.log_worker_event
```
````

````{py:function} printable_folders(folders: dict[str, typing.Optional[archivebox.core.models.Snapshot]], with_headers: bool = False) -> str
:canonical: archivebox.misc.logging_util.printable_folders

```{autodoc2-docstring} archivebox.misc.logging_util.printable_folders
```
````

````{py:function} printable_config(config: dict, prefix: str = '') -> str
:canonical: archivebox.misc.logging_util.printable_config

```{autodoc2-docstring} archivebox.misc.logging_util.printable_config
```
````

````{py:function} printable_folder_status(name: str, folder: dict) -> str
:canonical: archivebox.misc.logging_util.printable_folder_status

```{autodoc2-docstring} archivebox.misc.logging_util.printable_folder_status
```
````

````{py:function} printable_dependency_version(name: str, dependency: dict) -> str
:canonical: archivebox.misc.logging_util.printable_dependency_version

```{autodoc2-docstring} archivebox.misc.logging_util.printable_dependency_version
```
````
