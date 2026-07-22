# {py:mod}`archivebox.config.paths`

```{py:module} archivebox.config.paths
```

```{autodoc2-docstring} archivebox.config.paths
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_env_path <archivebox.config.paths._env_path>`
  - ```{autodoc2-docstring} archivebox.config.paths._env_path
    :summary:
    ```
* - {py:obj}`_get_collection_id <archivebox.config.paths._get_collection_id>`
  - ```{autodoc2-docstring} archivebox.config.paths._get_collection_id
    :summary:
    ```
* - {py:obj}`get_collection_id <archivebox.config.paths.get_collection_id>`
  - ```{autodoc2-docstring} archivebox.config.paths.get_collection_id
    :summary:
    ```
* - {py:obj}`get_machine_id <archivebox.config.paths.get_machine_id>`
  - ```{autodoc2-docstring} archivebox.config.paths.get_machine_id
    :summary:
    ```
* - {py:obj}`get_machine_type <archivebox.config.paths.get_machine_type>`
  - ```{autodoc2-docstring} archivebox.config.paths.get_machine_type
    :summary:
    ```
* - {py:obj}`dir_is_writable <archivebox.config.paths.dir_is_writable>`
  - ```{autodoc2-docstring} archivebox.config.paths.dir_is_writable
    :summary:
    ```
* - {py:obj}`assert_dir_can_contain_unix_sockets <archivebox.config.paths.assert_dir_can_contain_unix_sockets>`
  - ```{autodoc2-docstring} archivebox.config.paths.assert_dir_can_contain_unix_sockets
    :summary:
    ```
* - {py:obj}`create_and_chown_dir <archivebox.config.paths.create_and_chown_dir>`
  - ```{autodoc2-docstring} archivebox.config.paths.create_and_chown_dir
    :summary:
    ```
* - {py:obj}`tmp_dir_socket_path_is_short_enough <archivebox.config.paths.tmp_dir_socket_path_is_short_enough>`
  - ```{autodoc2-docstring} archivebox.config.paths.tmp_dir_socket_path_is_short_enough
    :summary:
    ```
* - {py:obj}`tmp_dir_candidates <archivebox.config.paths.tmp_dir_candidates>`
  - ```{autodoc2-docstring} archivebox.config.paths.tmp_dir_candidates
    :summary:
    ```
* - {py:obj}`get_or_create_working_tmp_dir <archivebox.config.paths.get_or_create_working_tmp_dir>`
  - ```{autodoc2-docstring} archivebox.config.paths.get_or_create_working_tmp_dir
    :summary:
    ```
* - {py:obj}`get_or_create_working_lib_dir <archivebox.config.paths.get_or_create_working_lib_dir>`
  - ```{autodoc2-docstring} archivebox.config.paths.get_or_create_working_lib_dir
    :summary:
    ```
* - {py:obj}`get_data_locations <archivebox.config.paths.get_data_locations>`
  - ```{autodoc2-docstring} archivebox.config.paths.get_data_locations
    :summary:
    ```
* - {py:obj}`get_code_locations <archivebox.config.paths.get_code_locations>`
  - ```{autodoc2-docstring} archivebox.config.paths.get_code_locations
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PACKAGE_DIR <archivebox.config.paths.PACKAGE_DIR>`
  - ```{autodoc2-docstring} archivebox.config.paths.PACKAGE_DIR
    :summary:
    ```
* - {py:obj}`DATA_DIR <archivebox.config.paths.DATA_DIR>`
  - ```{autodoc2-docstring} archivebox.config.paths.DATA_DIR
    :summary:
    ```
* - {py:obj}`MAX_TMP_SOCKET_URL_LENGTH <archivebox.config.paths.MAX_TMP_SOCKET_URL_LENGTH>`
  - ```{autodoc2-docstring} archivebox.config.paths.MAX_TMP_SOCKET_URL_LENGTH
    :summary:
    ```
* - {py:obj}`SUPERVISORD_SOCKET_FILENAME <archivebox.config.paths.SUPERVISORD_SOCKET_FILENAME>`
  - ```{autodoc2-docstring} archivebox.config.paths.SUPERVISORD_SOCKET_FILENAME
    :summary:
    ```
* - {py:obj}`ARCHIVE_DIR <archivebox.config.paths.ARCHIVE_DIR>`
  - ```{autodoc2-docstring} archivebox.config.paths.ARCHIVE_DIR
    :summary:
    ```
* - {py:obj}`USERS_DIR <archivebox.config.paths.USERS_DIR>`
  - ```{autodoc2-docstring} archivebox.config.paths.USERS_DIR
    :summary:
    ```
* - {py:obj}`IN_DOCKER <archivebox.config.paths.IN_DOCKER>`
  - ```{autodoc2-docstring} archivebox.config.paths.IN_DOCKER
    :summary:
    ```
* - {py:obj}`DATABASE_FILE <archivebox.config.paths.DATABASE_FILE>`
  - ```{autodoc2-docstring} archivebox.config.paths.DATABASE_FILE
    :summary:
    ```
````

### API

````{py:data} PACKAGE_DIR
:canonical: archivebox.config.paths.PACKAGE_DIR
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} archivebox.config.paths.PACKAGE_DIR
```

````

````{py:data} DATA_DIR
:canonical: archivebox.config.paths.DATA_DIR
:type: pathlib.Path
:value: >
   'resolve(...)'

```{autodoc2-docstring} archivebox.config.paths.DATA_DIR
```

````

````{py:data} MAX_TMP_SOCKET_URL_LENGTH
:canonical: archivebox.config.paths.MAX_TMP_SOCKET_URL_LENGTH
:value: >
   90

```{autodoc2-docstring} archivebox.config.paths.MAX_TMP_SOCKET_URL_LENGTH
```

````

````{py:data} SUPERVISORD_SOCKET_FILENAME
:canonical: archivebox.config.paths.SUPERVISORD_SOCKET_FILENAME
:value: >
   'supervisord.sock'

```{autodoc2-docstring} archivebox.config.paths.SUPERVISORD_SOCKET_FILENAME
```

````

````{py:function} _env_path(key: str, default: pathlib.Path) -> pathlib.Path
:canonical: archivebox.config.paths._env_path

```{autodoc2-docstring} archivebox.config.paths._env_path
```
````

````{py:data} ARCHIVE_DIR
:canonical: archivebox.config.paths.ARCHIVE_DIR
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} archivebox.config.paths.ARCHIVE_DIR
```

````

````{py:data} USERS_DIR
:canonical: archivebox.config.paths.USERS_DIR
:type: pathlib.Path
:value: >
   None

```{autodoc2-docstring} archivebox.config.paths.USERS_DIR
```

````

````{py:data} IN_DOCKER
:canonical: archivebox.config.paths.IN_DOCKER
:value: >
   None

```{autodoc2-docstring} archivebox.config.paths.IN_DOCKER
```

````

````{py:data} DATABASE_FILE
:canonical: archivebox.config.paths.DATABASE_FILE
:value: >
   None

```{autodoc2-docstring} archivebox.config.paths.DATABASE_FILE
```

````

````{py:function} _get_collection_id(DATA_DIR=DATA_DIR, force_create=False) -> str
:canonical: archivebox.config.paths._get_collection_id

```{autodoc2-docstring} archivebox.config.paths._get_collection_id
```
````

````{py:function} get_collection_id(DATA_DIR=DATA_DIR) -> str
:canonical: archivebox.config.paths.get_collection_id

```{autodoc2-docstring} archivebox.config.paths.get_collection_id
```
````

````{py:function} get_machine_id() -> str
:canonical: archivebox.config.paths.get_machine_id

```{autodoc2-docstring} archivebox.config.paths.get_machine_id
```
````

````{py:function} get_machine_type() -> str
:canonical: archivebox.config.paths.get_machine_type

```{autodoc2-docstring} archivebox.config.paths.get_machine_type
```
````

````{py:function} dir_is_writable(dir_path: pathlib.Path, uid: int | None = None, gid: int | None = None, fallback=True, chown=True) -> bool
:canonical: archivebox.config.paths.dir_is_writable

```{autodoc2-docstring} archivebox.config.paths.dir_is_writable
```
````

````{py:function} assert_dir_can_contain_unix_sockets(dir_path: pathlib.Path) -> bool
:canonical: archivebox.config.paths.assert_dir_can_contain_unix_sockets

```{autodoc2-docstring} archivebox.config.paths.assert_dir_can_contain_unix_sockets
```
````

````{py:function} create_and_chown_dir(dir_path: pathlib.Path) -> None
:canonical: archivebox.config.paths.create_and_chown_dir

```{autodoc2-docstring} archivebox.config.paths.create_and_chown_dir
```
````

````{py:function} tmp_dir_socket_path_is_short_enough(dir_path: pathlib.Path) -> bool
:canonical: archivebox.config.paths.tmp_dir_socket_path_is_short_enough

```{autodoc2-docstring} archivebox.config.paths.tmp_dir_socket_path_is_short_enough
```
````

````{py:function} tmp_dir_candidates(config: archivebox.config.common.ArchiveBoxConfig) -> list[pathlib.Path]
:canonical: archivebox.config.paths.tmp_dir_candidates

```{autodoc2-docstring} archivebox.config.paths.tmp_dir_candidates
```
````

````{py:function} get_or_create_working_tmp_dir(autofix=True, quiet=True, config: ArchiveBoxConfig | None = None, **config_kwargs)
:canonical: archivebox.config.paths.get_or_create_working_tmp_dir

```{autodoc2-docstring} archivebox.config.paths.get_or_create_working_tmp_dir
```
````

````{py:function} get_or_create_working_lib_dir(autofix=True, quiet=False, config: ArchiveBoxConfig | None = None, **config_kwargs)
:canonical: archivebox.config.paths.get_or_create_working_lib_dir

```{autodoc2-docstring} archivebox.config.paths.get_or_create_working_lib_dir
```
````

````{py:function} get_data_locations(config: ArchiveBoxConfig | None = None, **config_kwargs)
:canonical: archivebox.config.paths.get_data_locations

```{autodoc2-docstring} archivebox.config.paths.get_data_locations
```
````

````{py:function} get_code_locations(config: ArchiveBoxConfig | None = None, **config_kwargs)
:canonical: archivebox.config.paths.get_code_locations

```{autodoc2-docstring} archivebox.config.paths.get_code_locations
```
````
