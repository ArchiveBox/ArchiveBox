# {py:mod}`archivebox`

```{py:module} archivebox
```

```{autodoc2-docstring} archivebox
:allowtitles:
```

## Subpackages

```{toctree}
:titlesonly:
:maxdepth: 3

archivebox.misc
archivebox.core
archivebox.config
archivebox.plugins
archivebox.ldap
archivebox.mcp
archivebox.crawls
archivebox.cli
archivebox.search
archivebox.personas
archivebox.progressmonitor
archivebox.machine
archivebox.api
archivebox.workers
archivebox.base_models
archivebox.services
```

## Submodules

```{toctree}
:titlesonly:
:maxdepth: 1

archivebox.uuid_compat
archivebox.manage
archivebox.__main__
```

## Package Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_ReconfigurableStream <archivebox._ReconfigurableStream>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`__getattr__ <archivebox.__getattr__>`
  - ```{autodoc2-docstring} archivebox.__getattr__
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ASCII_LOGO <archivebox.ASCII_LOGO>`
  - ```{autodoc2-docstring} archivebox.ASCII_LOGO
    :summary:
    ```
* - {py:obj}`PACKAGE_DIR <archivebox.PACKAGE_DIR>`
  - ```{autodoc2-docstring} archivebox.PACKAGE_DIR
    :summary:
    ```
* - {py:obj}`__version__ <archivebox.__version__>`
  - ```{autodoc2-docstring} archivebox.__version__
    :summary:
    ```
* - {py:obj}`__author__ <archivebox.__author__>`
  - ```{autodoc2-docstring} archivebox.__author__
    :summary:
    ```
* - {py:obj}`__license__ <archivebox.__license__>`
  - ```{autodoc2-docstring} archivebox.__license__
    :summary:
    ```
* - {py:obj}`__all__ <archivebox.__all__>`
  - ```{autodoc2-docstring} archivebox.__all__
    :summary:
    ```
* - {py:obj}`ASCII_ICON <archivebox.ASCII_ICON>`
  - ```{autodoc2-docstring} archivebox.ASCII_ICON
    :summary:
    ```
````

### API

`````{py:class} _ReconfigurableStream
:canonical: archivebox._ReconfigurableStream

Bases: {py:obj}`typing.Protocol`

````{py:method} reconfigure(*, line_buffering: bool) -> object
:canonical: archivebox._ReconfigurableStream.reconfigure

```{autodoc2-docstring} archivebox._ReconfigurableStream.reconfigure
```

````

`````

````{py:data} ASCII_LOGO
:canonical: archivebox.ASCII_LOGO
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.ASCII_LOGO
```

````

````{py:data} PACKAGE_DIR
:canonical: archivebox.PACKAGE_DIR
:value: >
   None

```{autodoc2-docstring} archivebox.PACKAGE_DIR
```

````

````{py:data} __version__
:canonical: archivebox.__version__
:value: >
   None

```{autodoc2-docstring} archivebox.__version__
```

````

````{py:data} __author__
:canonical: archivebox.__author__
:value: >
   'ArchiveBox'

```{autodoc2-docstring} archivebox.__author__
```

````

````{py:data} __license__
:canonical: archivebox.__license__
:value: >
   'MIT'

```{autodoc2-docstring} archivebox.__license__
```

````

````{py:function} __getattr__(name: str)
:canonical: archivebox.__getattr__

```{autodoc2-docstring} archivebox.__getattr__
```
````

````{py:data} __all__
:canonical: archivebox.__all__
:value: >
   ('ASCII_LOGO', 'ASCII_ICON', 'PACKAGE_DIR', 'DATA_DIR', 'CONSTANTS', 'VERSION', 'BUILTIN_PLUGINS_DIR...

```{autodoc2-docstring} archivebox.__all__
```

````

````{py:data} ASCII_ICON
:canonical: archivebox.ASCII_ICON
:value: <Multiline-String>

```{autodoc2-docstring} archivebox.ASCII_ICON
```

````
