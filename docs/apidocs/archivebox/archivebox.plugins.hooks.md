# {py:mod}`archivebox.plugins.hooks`

```{py:module} archivebox.plugins.hooks
```

```{autodoc2-docstring} archivebox.plugins.hooks
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`is_background_hook <archivebox.plugins.hooks.is_background_hook>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.is_background_hook
    :summary:
    ```
* - {py:obj}`normalize_hook_event_name <archivebox.plugins.hooks.normalize_hook_event_name>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.normalize_hook_event_name
    :summary:
    ```
* - {py:obj}`discover_hooks <archivebox.plugins.hooks.discover_hooks>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.discover_hooks
    :summary:
    ```
* - {py:obj}`collect_urls_from_plugins <archivebox.plugins.hooks.collect_urls_from_plugins>`
  - ```{autodoc2-docstring} archivebox.plugins.hooks.collect_urls_from_plugins
    :summary:
    ```
````

### API

````{py:function} is_background_hook(hook_name: str) -> bool
:canonical: archivebox.plugins.hooks.is_background_hook

```{autodoc2-docstring} archivebox.plugins.hooks.is_background_hook
```
````

````{py:function} normalize_hook_event_name(event_name: str) -> str | None
:canonical: archivebox.plugins.hooks.normalize_hook_event_name

```{autodoc2-docstring} archivebox.plugins.hooks.normalize_hook_event_name
```
````

````{py:function} discover_hooks(event_name: str, filter_disabled: bool = True, config: archivebox.plugins.discovery.ConfigLookup | None = None, **config_kwargs: typing.Any) -> list[pathlib.Path]
:canonical: archivebox.plugins.hooks.discover_hooks

```{autodoc2-docstring} archivebox.plugins.hooks.discover_hooks
```
````

````{py:function} collect_urls_from_plugins(snapshot_dir: pathlib.Path) -> list[dict[str, typing.Any]]
:canonical: archivebox.plugins.hooks.collect_urls_from_plugins

```{autodoc2-docstring} archivebox.plugins.hooks.collect_urls_from_plugins
```
````
