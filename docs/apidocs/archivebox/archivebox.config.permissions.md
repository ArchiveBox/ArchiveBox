# {py:mod}`archivebox.config.permissions`

```{py:module} archivebox.config.permissions
```

```{autodoc2-docstring} archivebox.config.permissions
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`drop_privileges <archivebox.config.permissions.drop_privileges>`
  - ```{autodoc2-docstring} archivebox.config.permissions.drop_privileges
    :summary:
    ```
* - {py:obj}`SudoPermission <archivebox.config.permissions.SudoPermission>`
  - ```{autodoc2-docstring} archivebox.config.permissions.SudoPermission
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DATA_DIR <archivebox.config.permissions.DATA_DIR>`
  - ```{autodoc2-docstring} archivebox.config.permissions.DATA_DIR
    :summary:
    ```
* - {py:obj}`DEFAULT_UID <archivebox.config.permissions.DEFAULT_UID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.DEFAULT_UID
    :summary:
    ```
* - {py:obj}`DEFAULT_GID <archivebox.config.permissions.DEFAULT_GID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.DEFAULT_GID
    :summary:
    ```
* - {py:obj}`RUNNING_AS_UID <archivebox.config.permissions.RUNNING_AS_UID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.RUNNING_AS_UID
    :summary:
    ```
* - {py:obj}`RUNNING_AS_GID <archivebox.config.permissions.RUNNING_AS_GID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.RUNNING_AS_GID
    :summary:
    ```
* - {py:obj}`EUID <archivebox.config.permissions.EUID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.EUID
    :summary:
    ```
* - {py:obj}`EGID <archivebox.config.permissions.EGID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.EGID
    :summary:
    ```
* - {py:obj}`SUDO_UID <archivebox.config.permissions.SUDO_UID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.SUDO_UID
    :summary:
    ```
* - {py:obj}`SUDO_GID <archivebox.config.permissions.SUDO_GID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.SUDO_GID
    :summary:
    ```
* - {py:obj}`USER <archivebox.config.permissions.USER>`
  - ```{autodoc2-docstring} archivebox.config.permissions.USER
    :summary:
    ```
* - {py:obj}`HOSTNAME <archivebox.config.permissions.HOSTNAME>`
  - ```{autodoc2-docstring} archivebox.config.permissions.HOSTNAME
    :summary:
    ```
* - {py:obj}`IS_ROOT <archivebox.config.permissions.IS_ROOT>`
  - ```{autodoc2-docstring} archivebox.config.permissions.IS_ROOT
    :summary:
    ```
* - {py:obj}`IN_DOCKER <archivebox.config.permissions.IN_DOCKER>`
  - ```{autodoc2-docstring} archivebox.config.permissions.IN_DOCKER
    :summary:
    ```
* - {py:obj}`FALLBACK_UID <archivebox.config.permissions.FALLBACK_UID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.FALLBACK_UID
    :summary:
    ```
* - {py:obj}`FALLBACK_GID <archivebox.config.permissions.FALLBACK_GID>`
  - ```{autodoc2-docstring} archivebox.config.permissions.FALLBACK_GID
    :summary:
    ```
* - {py:obj}`ARCHIVEBOX_USER_EXISTS <archivebox.config.permissions.ARCHIVEBOX_USER_EXISTS>`
  - ```{autodoc2-docstring} archivebox.config.permissions.ARCHIVEBOX_USER_EXISTS
    :summary:
    ```
````

### API

````{py:data} DATA_DIR
:canonical: archivebox.config.permissions.DATA_DIR
:value: >
   'Path(...)'

```{autodoc2-docstring} archivebox.config.permissions.DATA_DIR
```

````

````{py:data} DEFAULT_UID
:canonical: archivebox.config.permissions.DEFAULT_UID
:value: >
   911

```{autodoc2-docstring} archivebox.config.permissions.DEFAULT_UID
```

````

````{py:data} DEFAULT_GID
:canonical: archivebox.config.permissions.DEFAULT_GID
:value: >
   911

```{autodoc2-docstring} archivebox.config.permissions.DEFAULT_GID
```

````

````{py:data} RUNNING_AS_UID
:canonical: archivebox.config.permissions.RUNNING_AS_UID
:value: >
   'getuid(...)'

```{autodoc2-docstring} archivebox.config.permissions.RUNNING_AS_UID
```

````

````{py:data} RUNNING_AS_GID
:canonical: archivebox.config.permissions.RUNNING_AS_GID
:value: >
   'getgid(...)'

```{autodoc2-docstring} archivebox.config.permissions.RUNNING_AS_GID
```

````

````{py:data} EUID
:canonical: archivebox.config.permissions.EUID
:value: >
   'geteuid(...)'

```{autodoc2-docstring} archivebox.config.permissions.EUID
```

````

````{py:data} EGID
:canonical: archivebox.config.permissions.EGID
:value: >
   'getegid(...)'

```{autodoc2-docstring} archivebox.config.permissions.EGID
```

````

````{py:data} SUDO_UID
:canonical: archivebox.config.permissions.SUDO_UID
:value: >
   'int(...)'

```{autodoc2-docstring} archivebox.config.permissions.SUDO_UID
```

````

````{py:data} SUDO_GID
:canonical: archivebox.config.permissions.SUDO_GID
:value: >
   'int(...)'

```{autodoc2-docstring} archivebox.config.permissions.SUDO_GID
```

````

````{py:data} USER
:canonical: archivebox.config.permissions.USER
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.config.permissions.USER
```

````

````{py:data} HOSTNAME
:canonical: archivebox.config.permissions.HOSTNAME
:type: str
:value: >
   'cast(...)'

```{autodoc2-docstring} archivebox.config.permissions.HOSTNAME
```

````

````{py:data} IS_ROOT
:canonical: archivebox.config.permissions.IS_ROOT
:value: >
   None

```{autodoc2-docstring} archivebox.config.permissions.IS_ROOT
```

````

````{py:data} IN_DOCKER
:canonical: archivebox.config.permissions.IN_DOCKER
:value: >
   None

```{autodoc2-docstring} archivebox.config.permissions.IN_DOCKER
```

````

````{py:data} FALLBACK_UID
:canonical: archivebox.config.permissions.FALLBACK_UID
:value: >
   None

```{autodoc2-docstring} archivebox.config.permissions.FALLBACK_UID
```

````

````{py:data} FALLBACK_GID
:canonical: archivebox.config.permissions.FALLBACK_GID
:value: >
   None

```{autodoc2-docstring} archivebox.config.permissions.FALLBACK_GID
```

````

````{py:data} ARCHIVEBOX_USER_EXISTS
:canonical: archivebox.config.permissions.ARCHIVEBOX_USER_EXISTS
:value: >
   False

```{autodoc2-docstring} archivebox.config.permissions.ARCHIVEBOX_USER_EXISTS
```

````

````{py:function} drop_privileges()
:canonical: archivebox.config.permissions.drop_privileges

```{autodoc2-docstring} archivebox.config.permissions.drop_privileges
```
````

````{py:function} SudoPermission(uid=0, fallback=False)
:canonical: archivebox.config.permissions.SudoPermission

```{autodoc2-docstring} archivebox.config.permissions.SudoPermission
```
````
