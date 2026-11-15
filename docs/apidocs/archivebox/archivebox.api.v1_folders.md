# {py:mod}`archivebox.api.v1_folders`

```{py:module} archivebox.api.v1_folders
```

```{autodoc2-docstring} archivebox.api.v1_folders
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`FolderSchema <archivebox.api.v1_folders.FolderSchema>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema
    :summary:
    ```
* - {py:obj}`FolderCreate <archivebox.api.v1_folders.FolderCreate>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.FolderCreate
    :summary:
    ```
* - {py:obj}`FolderUpdate <archivebox.api.v1_folders.FolderUpdate>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.FolderUpdate
    :summary:
    ```
* - {py:obj}`FolderSelection <archivebox.api.v1_folders.FolderSelection>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.FolderSelection
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`list_folders <archivebox.api.v1_folders.list_folders>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.list_folders
    :summary:
    ```
* - {py:obj}`folder_rules <archivebox.api.v1_folders.folder_rules>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.folder_rules
    :summary:
    ```
* - {py:obj}`create_folder <archivebox.api.v1_folders.create_folder>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.create_folder
    :summary:
    ```
* - {py:obj}`get_folder <archivebox.api.v1_folders.get_folder>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.get_folder
    :summary:
    ```
* - {py:obj}`update_folder <archivebox.api.v1_folders.update_folder>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.update_folder
    :summary:
    ```
* - {py:obj}`delete_folder <archivebox.api.v1_folders.delete_folder>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.delete_folder
    :summary:
    ```
* - {py:obj}`move_snapshots <archivebox.api.v1_folders.move_snapshots>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.move_snapshots
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`router <archivebox.api.v1_folders.router>`
  - ```{autodoc2-docstring} archivebox.api.v1_folders.router
    :summary:
    ```
````

### API

````{py:data} router
:canonical: archivebox.api.v1_folders.router
:value: >
   'Router(...)'

```{autodoc2-docstring} archivebox.api.v1_folders.router
```

````

`````{py:class} FolderSchema
:canonical: archivebox.api.v1_folders.FolderSchema

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema
```

````{py:attribute} type
:canonical: archivebox.api.v1_folders.FolderSchema.type
:type: str
:value: >
   'Folder'

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.type
```

````

````{py:attribute} id
:canonical: archivebox.api.v1_folders.FolderSchema.id
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.id
```

````

````{py:attribute} name
:canonical: archivebox.api.v1_folders.FolderSchema.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.name
```

````

````{py:attribute} parent_id
:canonical: archivebox.api.v1_folders.FolderSchema.parent_id
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.parent_id
```

````

````{py:attribute} parent_name
:canonical: archivebox.api.v1_folders.FolderSchema.parent_name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.parent_name
```

````

````{py:attribute} created_by_id
:canonical: archivebox.api.v1_folders.FolderSchema.created_by_id
:type: int | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.created_by_id
```

````

````{py:attribute} created_by_username
:canonical: archivebox.api.v1_folders.FolderSchema.created_by_username
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.created_by_username
```

````

````{py:attribute} position
:canonical: archivebox.api.v1_folders.FolderSchema.position
:type: int
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.position
```

````

````{py:attribute} rules
:canonical: archivebox.api.v1_folders.FolderSchema.rules
:type: dict | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.rules
```

````

````{py:attribute} is_smart
:canonical: archivebox.api.v1_folders.FolderSchema.is_smart
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.is_smart
```

````

````{py:attribute} is_container
:canonical: archivebox.api.v1_folders.FolderSchema.is_container
:type: bool
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSchema.is_container
```

````

`````

`````{py:class} FolderCreate
:canonical: archivebox.api.v1_folders.FolderCreate

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_folders.FolderCreate
```

````{py:attribute} name
:canonical: archivebox.api.v1_folders.FolderCreate.name
:type: str
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderCreate.name
```

````

````{py:attribute} parent_id
:canonical: archivebox.api.v1_folders.FolderCreate.parent_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderCreate.parent_id
```

````

````{py:attribute} position
:canonical: archivebox.api.v1_folders.FolderCreate.position
:type: int
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.api.v1_folders.FolderCreate.position
```

````

````{py:attribute} rules
:canonical: archivebox.api.v1_folders.FolderCreate.rules
:type: dict | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderCreate.rules
```

````

`````

`````{py:class} FolderUpdate
:canonical: archivebox.api.v1_folders.FolderUpdate

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_folders.FolderUpdate
```

````{py:attribute} name
:canonical: archivebox.api.v1_folders.FolderUpdate.name
:type: str | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderUpdate.name
```

````

````{py:attribute} parent_id
:canonical: archivebox.api.v1_folders.FolderUpdate.parent_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderUpdate.parent_id
```

````

````{py:attribute} position
:canonical: archivebox.api.v1_folders.FolderUpdate.position
:type: int | None
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.api.v1_folders.FolderUpdate.position
```

````

````{py:attribute} rules
:canonical: archivebox.api.v1_folders.FolderUpdate.rules
:type: dict | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderUpdate.rules
```

````

`````

`````{py:class} FolderSelection
:canonical: archivebox.api.v1_folders.FolderSelection

Bases: {py:obj}`ninja.Schema`

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSelection
```

````{py:attribute} snapshot_ids
:canonical: archivebox.api.v1_folders.FolderSelection.snapshot_ids
:type: list[uuid.UUID]
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSelection.snapshot_ids
```

````

````{py:attribute} destination_id
:canonical: archivebox.api.v1_folders.FolderSelection.destination_id
:type: uuid.UUID | None
:value: >
   None

```{autodoc2-docstring} archivebox.api.v1_folders.FolderSelection.destination_id
```

````

`````

````{py:function} list_folders(request, format: str | None = None)
:canonical: archivebox.api.v1_folders.list_folders

```{autodoc2-docstring} archivebox.api.v1_folders.list_folders
```
````

````{py:function} folder_rules(request)
:canonical: archivebox.api.v1_folders.folder_rules

```{autodoc2-docstring} archivebox.api.v1_folders.folder_rules
```
````

````{py:function} create_folder(request, data: archivebox.api.v1_folders.FolderCreate)
:canonical: archivebox.api.v1_folders.create_folder

```{autodoc2-docstring} archivebox.api.v1_folders.create_folder
```
````

````{py:function} get_folder(request, folder_id: uuid.UUID)
:canonical: archivebox.api.v1_folders.get_folder

```{autodoc2-docstring} archivebox.api.v1_folders.get_folder
```
````

````{py:function} update_folder(request, folder_id: uuid.UUID, data: archivebox.api.v1_folders.FolderUpdate)
:canonical: archivebox.api.v1_folders.update_folder

```{autodoc2-docstring} archivebox.api.v1_folders.update_folder
```
````

````{py:function} delete_folder(request, folder_id: uuid.UUID)
:canonical: archivebox.api.v1_folders.delete_folder

```{autodoc2-docstring} archivebox.api.v1_folders.delete_folder
```
````

````{py:function} move_snapshots(request, data: archivebox.api.v1_folders.FolderSelection)
:canonical: archivebox.api.v1_folders.move_snapshots

```{autodoc2-docstring} archivebox.api.v1_folders.move_snapshots
```
````
