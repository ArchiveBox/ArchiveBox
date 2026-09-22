# {py:mod}`archivebox.personas.importers`

```{py:module} archivebox.personas.importers
```

```{autodoc2-docstring} archivebox.personas.importers
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PersonaImportSource <archivebox.personas.importers.PersonaImportSource>`
  - ```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource
    :summary:
    ```
* - {py:obj}`PersonaImportResult <archivebox.personas.importers.PersonaImportResult>`
  - ```{autodoc2-docstring} archivebox.personas.importers.PersonaImportResult
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_path_exists <archivebox.personas.importers._path_exists>`
  - ```{autodoc2-docstring} archivebox.personas.importers._path_exists
    :summary:
    ```
* - {py:obj}`_path_is_dir <archivebox.personas.importers._path_is_dir>`
  - ```{autodoc2-docstring} archivebox.personas.importers._path_is_dir
    :summary:
    ```
* - {py:obj}`_iter_children <archivebox.personas.importers._iter_children>`
  - ```{autodoc2-docstring} archivebox.personas.importers._iter_children
    :summary:
    ```
* - {py:obj}`_is_copyable_profile_entry <archivebox.personas.importers._is_copyable_profile_entry>`
  - ```{autodoc2-docstring} archivebox.personas.importers._is_copyable_profile_entry
    :summary:
    ```
* - {py:obj}`profile_copy_ignore <archivebox.personas.importers.profile_copy_ignore>`
  - ```{autodoc2-docstring} archivebox.personas.importers.profile_copy_ignore
    :summary:
    ```
* - {py:obj}`get_chrome_user_data_dir <archivebox.personas.importers.get_chrome_user_data_dir>`
  - ```{autodoc2-docstring} archivebox.personas.importers.get_chrome_user_data_dir
    :summary:
    ```
* - {py:obj}`get_brave_user_data_dir <archivebox.personas.importers.get_brave_user_data_dir>`
  - ```{autodoc2-docstring} archivebox.personas.importers.get_brave_user_data_dir
    :summary:
    ```
* - {py:obj}`get_edge_user_data_dir <archivebox.personas.importers.get_edge_user_data_dir>`
  - ```{autodoc2-docstring} archivebox.personas.importers.get_edge_user_data_dir
    :summary:
    ```
* - {py:obj}`validate_persona_name <archivebox.personas.importers.validate_persona_name>`
  - ```{autodoc2-docstring} archivebox.personas.importers.validate_persona_name
    :summary:
    ```
* - {py:obj}`discover_local_browser_profiles <archivebox.personas.importers.discover_local_browser_profiles>`
  - ```{autodoc2-docstring} archivebox.personas.importers.discover_local_browser_profiles
    :summary:
    ```
* - {py:obj}`discover_persona_template_profiles <archivebox.personas.importers.discover_persona_template_profiles>`
  - ```{autodoc2-docstring} archivebox.personas.importers.discover_persona_template_profiles
    :summary:
    ```
* - {py:obj}`resolve_browser_import_source <archivebox.personas.importers.resolve_browser_import_source>`
  - ```{autodoc2-docstring} archivebox.personas.importers.resolve_browser_import_source
    :summary:
    ```
* - {py:obj}`resolve_browser_profile_source <archivebox.personas.importers.resolve_browser_profile_source>`
  - ```{autodoc2-docstring} archivebox.personas.importers.resolve_browser_profile_source
    :summary:
    ```
* - {py:obj}`resolve_custom_import_source <archivebox.personas.importers.resolve_custom_import_source>`
  - ```{autodoc2-docstring} archivebox.personas.importers.resolve_custom_import_source
    :summary:
    ```
* - {py:obj}`pick_default_profile_dir <archivebox.personas.importers.pick_default_profile_dir>`
  - ```{autodoc2-docstring} archivebox.personas.importers.pick_default_profile_dir
    :summary:
    ```
* - {py:obj}`import_persona_from_source <archivebox.personas.importers.import_persona_from_source>`
  - ```{autodoc2-docstring} archivebox.personas.importers.import_persona_from_source
    :summary:
    ```
* - {py:obj}`copy_browser_user_data_dir <archivebox.personas.importers.copy_browser_user_data_dir>`
  - ```{autodoc2-docstring} archivebox.personas.importers.copy_browser_user_data_dir
    :summary:
    ```
* - {py:obj}`export_browser_state <archivebox.personas.importers.export_browser_state>`
  - ```{autodoc2-docstring} archivebox.personas.importers.export_browser_state
    :summary:
    ```
* - {py:obj}`_list_profile_names <archivebox.personas.importers._list_profile_names>`
  - ```{autodoc2-docstring} archivebox.personas.importers._list_profile_names
    :summary:
    ```
* - {py:obj}`_looks_like_profile_dir <archivebox.personas.importers._looks_like_profile_dir>`
  - ```{autodoc2-docstring} archivebox.personas.importers._looks_like_profile_dir
    :summary:
    ```
* - {py:obj}`_looks_like_cdp_url <archivebox.personas.importers._looks_like_cdp_url>`
  - ```{autodoc2-docstring} archivebox.personas.importers._looks_like_cdp_url
    :summary:
    ```
* - {py:obj}`_parse_netscape_cookies <archivebox.personas.importers._parse_netscape_cookies>`
  - ```{autodoc2-docstring} archivebox.personas.importers._parse_netscape_cookies
    :summary:
    ```
* - {py:obj}`_write_netscape_cookies <archivebox.personas.importers._write_netscape_cookies>`
  - ```{autodoc2-docstring} archivebox.personas.importers._write_netscape_cookies
    :summary:
    ```
* - {py:obj}`_merge_netscape_cookies <archivebox.personas.importers._merge_netscape_cookies>`
  - ```{autodoc2-docstring} archivebox.personas.importers._merge_netscape_cookies
    :summary:
    ```
* - {py:obj}`_merge_auth_storage <archivebox.personas.importers._merge_auth_storage>`
  - ```{autodoc2-docstring} archivebox.personas.importers._merge_auth_storage
    :summary:
    ```
* - {py:obj}`_load_auth_storage <archivebox.personas.importers._load_auth_storage>`
  - ```{autodoc2-docstring} archivebox.personas.importers._load_auth_storage
    :summary:
    ```
* - {py:obj}`_merge_cookie_dicts <archivebox.personas.importers._merge_cookie_dicts>`
  - ```{autodoc2-docstring} archivebox.personas.importers._merge_cookie_dicts
    :summary:
    ```
* - {py:obj}`_apply_imported_user_agent <archivebox.personas.importers._apply_imported_user_agent>`
  - ```{autodoc2-docstring} archivebox.personas.importers._apply_imported_user_agent
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BROWSER_LABELS <archivebox.personas.importers.BROWSER_LABELS>`
  - ```{autodoc2-docstring} archivebox.personas.importers.BROWSER_LABELS
    :summary:
    ```
* - {py:obj}`BROWSER_PROFILE_DIR_NAMES <archivebox.personas.importers.BROWSER_PROFILE_DIR_NAMES>`
  - ```{autodoc2-docstring} archivebox.personas.importers.BROWSER_PROFILE_DIR_NAMES
    :summary:
    ```
* - {py:obj}`VOLATILE_PROFILE_COPY_PATTERNS <archivebox.personas.importers.VOLATILE_PROFILE_COPY_PATTERNS>`
  - ```{autodoc2-docstring} archivebox.personas.importers.VOLATILE_PROFILE_COPY_PATTERNS
    :summary:
    ```
* - {py:obj}`PERSONA_PROFILE_DIR_CANDIDATES <archivebox.personas.importers.PERSONA_PROFILE_DIR_CANDIDATES>`
  - ```{autodoc2-docstring} archivebox.personas.importers.PERSONA_PROFILE_DIR_CANDIDATES
    :summary:
    ```
* - {py:obj}`BROWSER_PROFILE_FINDERS <archivebox.personas.importers.BROWSER_PROFILE_FINDERS>`
  - ```{autodoc2-docstring} archivebox.personas.importers.BROWSER_PROFILE_FINDERS
    :summary:
    ```
* - {py:obj}`CHROMIUM_BROWSERS <archivebox.personas.importers.CHROMIUM_BROWSERS>`
  - ```{autodoc2-docstring} archivebox.personas.importers.CHROMIUM_BROWSERS
    :summary:
    ```
* - {py:obj}`NETSCAPE_COOKIE_HEADER <archivebox.personas.importers.NETSCAPE_COOKIE_HEADER>`
  - ```{autodoc2-docstring} archivebox.personas.importers.NETSCAPE_COOKIE_HEADER
    :summary:
    ```
````

### API

````{py:data} BROWSER_LABELS
:canonical: archivebox.personas.importers.BROWSER_LABELS
:value: >
   None

```{autodoc2-docstring} archivebox.personas.importers.BROWSER_LABELS
```

````

````{py:data} BROWSER_PROFILE_DIR_NAMES
:canonical: archivebox.personas.importers.BROWSER_PROFILE_DIR_NAMES
:value: >
   ('Default', 'Profile ', 'Guest Profile')

```{autodoc2-docstring} archivebox.personas.importers.BROWSER_PROFILE_DIR_NAMES
```

````

````{py:data} VOLATILE_PROFILE_COPY_PATTERNS
:canonical: archivebox.personas.importers.VOLATILE_PROFILE_COPY_PATTERNS
:value: >
   ('Cache', 'Code Cache', 'GPUCache', 'ShaderCache', 'Service Worker', 'GCM Store', 'chrome-extension_...

```{autodoc2-docstring} archivebox.personas.importers.VOLATILE_PROFILE_COPY_PATTERNS
```

````

````{py:data} PERSONA_PROFILE_DIR_CANDIDATES
:canonical: archivebox.personas.importers.PERSONA_PROFILE_DIR_CANDIDATES
:value: >
   ('chrome_profile', 'chrome_user_data')

```{autodoc2-docstring} archivebox.personas.importers.PERSONA_PROFILE_DIR_CANDIDATES
```

````

````{py:function} _path_exists(path: pathlib.Path) -> bool
:canonical: archivebox.personas.importers._path_exists

```{autodoc2-docstring} archivebox.personas.importers._path_exists
```
````

````{py:function} _path_is_dir(path: pathlib.Path) -> bool
:canonical: archivebox.personas.importers._path_is_dir

```{autodoc2-docstring} archivebox.personas.importers._path_is_dir
```
````

````{py:function} _iter_children(path: pathlib.Path) -> list[pathlib.Path]
:canonical: archivebox.personas.importers._iter_children

```{autodoc2-docstring} archivebox.personas.importers._iter_children
```
````

````{py:function} _is_copyable_profile_entry(path: pathlib.Path) -> bool
:canonical: archivebox.personas.importers._is_copyable_profile_entry

```{autodoc2-docstring} archivebox.personas.importers._is_copyable_profile_entry
```
````

````{py:function} profile_copy_ignore(src: str, names: list[str]) -> set[str]
:canonical: archivebox.personas.importers.profile_copy_ignore

```{autodoc2-docstring} archivebox.personas.importers.profile_copy_ignore
```
````

`````{py:class} PersonaImportSource
:canonical: archivebox.personas.importers.PersonaImportSource

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource
```

````{py:attribute} kind
:canonical: archivebox.personas.importers.PersonaImportSource.kind
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.kind
```

````

````{py:attribute} browser
:canonical: archivebox.personas.importers.PersonaImportSource.browser
:type: str
:value: >
   'custom'

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.browser
```

````

````{py:attribute} source_name
:canonical: archivebox.personas.importers.PersonaImportSource.source_name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.source_name
```

````

````{py:attribute} user_data_dir
:canonical: archivebox.personas.importers.PersonaImportSource.user_data_dir
:type: pathlib.Path | None
:value: >
   None

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.user_data_dir
```

````

````{py:attribute} profile_dir
:canonical: archivebox.personas.importers.PersonaImportSource.profile_dir
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.profile_dir
```

````

````{py:attribute} browser_binary
:canonical: archivebox.personas.importers.PersonaImportSource.browser_binary
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.browser_binary
```

````

````{py:attribute} cdp_url
:canonical: archivebox.personas.importers.PersonaImportSource.cdp_url
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.cdp_url
```

````

````{py:property} browser_label
:canonical: archivebox.personas.importers.PersonaImportSource.browser_label
:type: str

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.browser_label
```

````

````{py:property} profile_path
:canonical: archivebox.personas.importers.PersonaImportSource.profile_path
:type: pathlib.Path | None

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.profile_path
```

````

````{py:property} display_label
:canonical: archivebox.personas.importers.PersonaImportSource.display_label
:type: str

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.display_label
```

````

````{py:property} choice_value
:canonical: archivebox.personas.importers.PersonaImportSource.choice_value
:type: str

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.choice_value
```

````

````{py:method} as_choice_label() -> django.utils.safestring.SafeString
:canonical: archivebox.personas.importers.PersonaImportSource.as_choice_label

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.as_choice_label
```

````

````{py:method} from_choice_value(value: str) -> archivebox.personas.importers.PersonaImportSource
:canonical: archivebox.personas.importers.PersonaImportSource.from_choice_value
:classmethod:

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportSource.from_choice_value
```

````

`````

`````{py:class} PersonaImportResult
:canonical: archivebox.personas.importers.PersonaImportResult

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportResult
```

````{py:attribute} source
:canonical: archivebox.personas.importers.PersonaImportResult.source
:type: archivebox.personas.importers.PersonaImportSource
:value: >
   None

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportResult.source
```

````

````{py:attribute} profile_copied
:canonical: archivebox.personas.importers.PersonaImportResult.profile_copied
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportResult.profile_copied
```

````

````{py:attribute} cookies_imported
:canonical: archivebox.personas.importers.PersonaImportResult.cookies_imported
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportResult.cookies_imported
```

````

````{py:attribute} storage_captured
:canonical: archivebox.personas.importers.PersonaImportResult.storage_captured
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportResult.storage_captured
```

````

````{py:attribute} user_agent_imported
:canonical: archivebox.personas.importers.PersonaImportResult.user_agent_imported
:type: bool
:value: >
   False

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportResult.user_agent_imported
```

````

````{py:attribute} warnings
:canonical: archivebox.personas.importers.PersonaImportResult.warnings
:type: list[str]
:value: >
   'field(...)'

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportResult.warnings
```

````

````{py:property} did_work
:canonical: archivebox.personas.importers.PersonaImportResult.did_work
:type: bool

```{autodoc2-docstring} archivebox.personas.importers.PersonaImportResult.did_work
```

````

`````

````{py:function} get_chrome_user_data_dir() -> pathlib.Path | None
:canonical: archivebox.personas.importers.get_chrome_user_data_dir

```{autodoc2-docstring} archivebox.personas.importers.get_chrome_user_data_dir
```
````

````{py:function} get_brave_user_data_dir() -> pathlib.Path | None
:canonical: archivebox.personas.importers.get_brave_user_data_dir

```{autodoc2-docstring} archivebox.personas.importers.get_brave_user_data_dir
```
````

````{py:function} get_edge_user_data_dir() -> pathlib.Path | None
:canonical: archivebox.personas.importers.get_edge_user_data_dir

```{autodoc2-docstring} archivebox.personas.importers.get_edge_user_data_dir
```
````

````{py:data} BROWSER_PROFILE_FINDERS
:canonical: archivebox.personas.importers.BROWSER_PROFILE_FINDERS
:value: >
   None

```{autodoc2-docstring} archivebox.personas.importers.BROWSER_PROFILE_FINDERS
```

````

````{py:data} CHROMIUM_BROWSERS
:canonical: archivebox.personas.importers.CHROMIUM_BROWSERS
:value: >
   'tuple(...)'

```{autodoc2-docstring} archivebox.personas.importers.CHROMIUM_BROWSERS
```

````

````{py:data} NETSCAPE_COOKIE_HEADER
:canonical: archivebox.personas.importers.NETSCAPE_COOKIE_HEADER
:value: >
   ['# Netscape HTTP Cookie File', '# https://curl.se/docs/http-cookies.html', '# This file was generat...

```{autodoc2-docstring} archivebox.personas.importers.NETSCAPE_COOKIE_HEADER
```

````

````{py:function} validate_persona_name(name: str) -> tuple[bool, str]
:canonical: archivebox.personas.importers.validate_persona_name

```{autodoc2-docstring} archivebox.personas.importers.validate_persona_name
```
````

````{py:function} discover_local_browser_profiles() -> list[archivebox.personas.importers.PersonaImportSource]
:canonical: archivebox.personas.importers.discover_local_browser_profiles

```{autodoc2-docstring} archivebox.personas.importers.discover_local_browser_profiles
```
````

````{py:function} discover_persona_template_profiles(personas_dir: pathlib.Path | None = None) -> list[archivebox.personas.importers.PersonaImportSource]
:canonical: archivebox.personas.importers.discover_persona_template_profiles

```{autodoc2-docstring} archivebox.personas.importers.discover_persona_template_profiles
```
````

````{py:function} resolve_browser_import_source(browser: str, profile_dir: str | None = None) -> archivebox.personas.importers.PersonaImportSource
:canonical: archivebox.personas.importers.resolve_browser_import_source

```{autodoc2-docstring} archivebox.personas.importers.resolve_browser_import_source
```
````

````{py:function} resolve_browser_profile_source(browser: str, user_data_dir: pathlib.Path, profile_dir: str, source_name: str | None = None, browser_binary: str | None = None) -> archivebox.personas.importers.PersonaImportSource
:canonical: archivebox.personas.importers.resolve_browser_profile_source

```{autodoc2-docstring} archivebox.personas.importers.resolve_browser_profile_source
```
````

````{py:function} resolve_custom_import_source(raw_value: str, profile_dir: str | None = None) -> archivebox.personas.importers.PersonaImportSource
:canonical: archivebox.personas.importers.resolve_custom_import_source

```{autodoc2-docstring} archivebox.personas.importers.resolve_custom_import_source
```
````

````{py:function} pick_default_profile_dir(user_data_dir: pathlib.Path) -> str | None
:canonical: archivebox.personas.importers.pick_default_profile_dir

```{autodoc2-docstring} archivebox.personas.importers.pick_default_profile_dir
```
````

````{py:function} import_persona_from_source(persona: archivebox.personas.models.Persona, source: archivebox.personas.importers.PersonaImportSource, *, copy_profile: bool = True, import_cookies: bool = True, capture_storage: bool = False) -> archivebox.personas.importers.PersonaImportResult
:canonical: archivebox.personas.importers.import_persona_from_source

```{autodoc2-docstring} archivebox.personas.importers.import_persona_from_source
```
````

````{py:function} copy_browser_user_data_dir(source_dir: pathlib.Path, destination_dir: pathlib.Path) -> None
:canonical: archivebox.personas.importers.copy_browser_user_data_dir

```{autodoc2-docstring} archivebox.personas.importers.copy_browser_user_data_dir
```
````

````{py:function} export_browser_state(*, user_data_dir: pathlib.Path | None = None, cdp_url: str | None = None, profile_dir: str | None = None, chrome_binary: str | None = None, cookies_output_file: pathlib.Path | None = None, auth_output_file: pathlib.Path | None = None) -> tuple[bool, dict | None, str]
:canonical: archivebox.personas.importers.export_browser_state

```{autodoc2-docstring} archivebox.personas.importers.export_browser_state
```
````

````{py:function} _list_profile_names(user_data_dir: pathlib.Path) -> list[str]
:canonical: archivebox.personas.importers._list_profile_names

```{autodoc2-docstring} archivebox.personas.importers._list_profile_names
```
````

````{py:function} _looks_like_profile_dir(path: pathlib.Path) -> bool
:canonical: archivebox.personas.importers._looks_like_profile_dir

```{autodoc2-docstring} archivebox.personas.importers._looks_like_profile_dir
```
````

````{py:function} _looks_like_cdp_url(value: str) -> bool
:canonical: archivebox.personas.importers._looks_like_cdp_url

```{autodoc2-docstring} archivebox.personas.importers._looks_like_cdp_url
```
````

````{py:function} _parse_netscape_cookies(path: pathlib.Path) -> dict[tuple[str, str, str], tuple[str, str, str, str, str, str, str]]
:canonical: archivebox.personas.importers._parse_netscape_cookies

```{autodoc2-docstring} archivebox.personas.importers._parse_netscape_cookies
```
````

````{py:function} _write_netscape_cookies(path: pathlib.Path, cookies: dict[tuple[str, str, str], tuple[str, str, str, str, str, str, str]]) -> None
:canonical: archivebox.personas.importers._write_netscape_cookies

```{autodoc2-docstring} archivebox.personas.importers._write_netscape_cookies
```
````

````{py:function} _merge_netscape_cookies(existing_file: pathlib.Path, new_file: pathlib.Path) -> None
:canonical: archivebox.personas.importers._merge_netscape_cookies

```{autodoc2-docstring} archivebox.personas.importers._merge_netscape_cookies
```
````

````{py:function} _merge_auth_storage(existing_file: pathlib.Path, new_file: pathlib.Path) -> None
:canonical: archivebox.personas.importers._merge_auth_storage

```{autodoc2-docstring} archivebox.personas.importers._merge_auth_storage
```
````

````{py:function} _load_auth_storage(path: pathlib.Path) -> dict
:canonical: archivebox.personas.importers._load_auth_storage

```{autodoc2-docstring} archivebox.personas.importers._load_auth_storage
```
````

````{py:function} _merge_cookie_dicts(existing: list[dict], new: list[dict]) -> list[dict]
:canonical: archivebox.personas.importers._merge_cookie_dicts

```{autodoc2-docstring} archivebox.personas.importers._merge_cookie_dicts
```
````

````{py:function} _apply_imported_user_agent(persona: archivebox.personas.models.Persona, auth_payload: dict | None) -> bool
:canonical: archivebox.personas.importers._apply_imported_user_agent

```{autodoc2-docstring} archivebox.personas.importers._apply_imported_user_agent
```
````
