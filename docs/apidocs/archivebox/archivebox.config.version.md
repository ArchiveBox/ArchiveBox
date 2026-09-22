# {py:mod}`archivebox.config.version`

```{py:module} archivebox.config.version
```

```{autodoc2-docstring} archivebox.config.version
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`detect_installed_version <archivebox.config.version.detect_installed_version>`
  - ```{autodoc2-docstring} archivebox.config.version.detect_installed_version
    :summary:
    ```
* - {py:obj}`get_COMMIT_HASH <archivebox.config.version.get_COMMIT_HASH>`
  - ```{autodoc2-docstring} archivebox.config.version.get_COMMIT_HASH
    :summary:
    ```
* - {py:obj}`get_BUILD_TIME <archivebox.config.version.get_BUILD_TIME>`
  - ```{autodoc2-docstring} archivebox.config.version.get_BUILD_TIME
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`IN_DOCKER <archivebox.config.version.IN_DOCKER>`
  - ```{autodoc2-docstring} archivebox.config.version.IN_DOCKER
    :summary:
    ```
* - {py:obj}`PACKAGE_DIR <archivebox.config.version.PACKAGE_DIR>`
  - ```{autodoc2-docstring} archivebox.config.version.PACKAGE_DIR
    :summary:
    ```
* - {py:obj}`VERSION <archivebox.config.version.VERSION>`
  - ```{autodoc2-docstring} archivebox.config.version.VERSION
    :summary:
    ```
````

### API

````{py:data} IN_DOCKER
:canonical: archivebox.config.version.IN_DOCKER
:value: >
   None

```{autodoc2-docstring} archivebox.config.version.IN_DOCKER
```

````

````{py:data} PACKAGE_DIR
:canonical: archivebox.config.version.PACKAGE_DIR
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} archivebox.config.version.PACKAGE_DIR
```

````

````{py:function} detect_installed_version(PACKAGE_DIR: pathlib.Path = PACKAGE_DIR)
:canonical: archivebox.config.version.detect_installed_version

```{autodoc2-docstring} archivebox.config.version.detect_installed_version
```
````

````{py:function} get_COMMIT_HASH() -> str | None
:canonical: archivebox.config.version.get_COMMIT_HASH

```{autodoc2-docstring} archivebox.config.version.get_COMMIT_HASH
```
````

````{py:function} get_BUILD_TIME() -> str
:canonical: archivebox.config.version.get_BUILD_TIME

```{autodoc2-docstring} archivebox.config.version.get_BUILD_TIME
```
````

````{py:data} VERSION
:canonical: archivebox.config.version.VERSION
:type: str
:value: >
   'detect_installed_version(...)'

```{autodoc2-docstring} archivebox.config.version.VERSION
```

````
