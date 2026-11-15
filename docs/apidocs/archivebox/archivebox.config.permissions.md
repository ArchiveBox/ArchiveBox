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

* - {py:obj}`is_root_identity <archivebox.config.permissions.is_root_identity>`
  - ```{autodoc2-docstring} archivebox.config.permissions.is_root_identity
    :summary:
    ```
* - {py:obj}`select_archivebox_user <archivebox.config.permissions.select_archivebox_user>`
  - ```{autodoc2-docstring} archivebox.config.permissions.select_archivebox_user
    :summary:
    ```
* - {py:obj}`get_or_create_archivebox_account <archivebox.config.permissions.get_or_create_archivebox_account>`
  - ```{autodoc2-docstring} archivebox.config.permissions.get_or_create_archivebox_account
    :summary:
    ```
* - {py:obj}`root_data_dir_handoff_paths <archivebox.config.permissions.root_data_dir_handoff_paths>`
  - ```{autodoc2-docstring} archivebox.config.permissions.root_data_dir_handoff_paths
    :summary:
    ```
* - {py:obj}`root_should_handoff_data_dir <archivebox.config.permissions.root_should_handoff_data_dir>`
  - ```{autodoc2-docstring} archivebox.config.permissions.root_should_handoff_data_dir
    :summary:
    ```
* - {py:obj}`root_parent_can_grant_group_traversal <archivebox.config.permissions.root_parent_can_grant_group_traversal>`
  - ```{autodoc2-docstring} archivebox.config.permissions.root_parent_can_grant_group_traversal
    :summary:
    ```
* - {py:obj}`grant_archivebox_group_traversal <archivebox.config.permissions.grant_archivebox_group_traversal>`
  - ```{autodoc2-docstring} archivebox.config.permissions.grant_archivebox_group_traversal
    :summary:
    ```
* - {py:obj}`handoff_root_owned_data_dir <archivebox.config.permissions.handoff_root_owned_data_dir>`
  - ```{autodoc2-docstring} archivebox.config.permissions.handoff_root_owned_data_dir
    :summary:
    ```
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
* - {py:obj}`ARCHIVEBOX_ACCOUNT <archivebox.config.permissions.ARCHIVEBOX_ACCOUNT>`
  - ```{autodoc2-docstring} archivebox.config.permissions.ARCHIVEBOX_ACCOUNT
    :summary:
    ```
* - {py:obj}`ARCHIVEBOX_USER_EXISTS <archivebox.config.permissions.ARCHIVEBOX_USER_EXISTS>`
  - ```{autodoc2-docstring} archivebox.config.permissions.ARCHIVEBOX_USER_EXISTS
    :summary:
    ```
* - {py:obj}`ROOT_HANDOFF_NAMES <archivebox.config.permissions.ROOT_HANDOFF_NAMES>`
  - ```{autodoc2-docstring} archivebox.config.permissions.ROOT_HANDOFF_NAMES
    :summary:
    ```
````

### API

````{py:function} is_root_identity(running_uid: int, effective_uid: int) -> bool
:canonical: archivebox.config.permissions.is_root_identity

```{autodoc2-docstring} archivebox.config.permissions.is_root_identity
```
````

````{py:function} select_archivebox_user(*, running_uid: int, running_gid: int, effective_uid: int, effective_gid: int, sudo_uid: int, sudo_gid: int, data_dir_uid: int, data_dir_gid: int, account_uid: int | None, account_gid: int | None, data_dir_owner_gid: int | None = None, data_dir_owner_exists: bool = True) -> tuple[int, int]
:canonical: archivebox.config.permissions.select_archivebox_user

```{autodoc2-docstring} archivebox.config.permissions.select_archivebox_user
```
````

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
   'is_root_identity(...)'

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

````{py:function} get_or_create_archivebox_account()
:canonical: archivebox.config.permissions.get_or_create_archivebox_account

```{autodoc2-docstring} archivebox.config.permissions.get_or_create_archivebox_account
```
````

````{py:data} ARCHIVEBOX_ACCOUNT
:canonical: archivebox.config.permissions.ARCHIVEBOX_ACCOUNT
:value: >
   'get_or_create_archivebox_account(...)'

```{autodoc2-docstring} archivebox.config.permissions.ARCHIVEBOX_ACCOUNT
```

````

````{py:data} ARCHIVEBOX_USER_EXISTS
:canonical: archivebox.config.permissions.ARCHIVEBOX_USER_EXISTS
:value: >
   False

```{autodoc2-docstring} archivebox.config.permissions.ARCHIVEBOX_USER_EXISTS
```

````

````{py:data} ROOT_HANDOFF_NAMES
:canonical: archivebox.config.permissions.ROOT_HANDOFF_NAMES
:value: >
   ('.archivebox_id', 'ArchiveBox.conf', 'index.sqlite3', 'index.sqlite3-shm', 'index.sqlite3-wal', 'ar...

```{autodoc2-docstring} archivebox.config.permissions.ROOT_HANDOFF_NAMES
```

````

````{py:function} root_data_dir_handoff_paths(data_dir: pathlib.Path, argv: list[str]) -> tuple[pathlib.Path, ...]
:canonical: archivebox.config.permissions.root_data_dir_handoff_paths

```{autodoc2-docstring} archivebox.config.permissions.root_data_dir_handoff_paths
```
````

````{py:function} root_should_handoff_data_dir(*, is_root: bool, data_dir_uid: int, account_uid: int | None, data_dir_owner_exists: bool = True) -> bool
:canonical: archivebox.config.permissions.root_should_handoff_data_dir

```{autodoc2-docstring} archivebox.config.permissions.root_should_handoff_data_dir
```
````

````{py:function} root_parent_can_grant_group_traversal(*, parent_uid: int, parent_gid: int, parent_mode: int, account_gid: int) -> bool
:canonical: archivebox.config.permissions.root_parent_can_grant_group_traversal

```{autodoc2-docstring} archivebox.config.permissions.root_parent_can_grant_group_traversal
```
````

````{py:function} grant_archivebox_group_traversal(path: pathlib.Path) -> None
:canonical: archivebox.config.permissions.grant_archivebox_group_traversal

```{autodoc2-docstring} archivebox.config.permissions.grant_archivebox_group_traversal
```
````

````{py:function} handoff_root_owned_data_dir() -> None
:canonical: archivebox.config.permissions.handoff_root_owned_data_dir

```{autodoc2-docstring} archivebox.config.permissions.handoff_root_owned_data_dir
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
