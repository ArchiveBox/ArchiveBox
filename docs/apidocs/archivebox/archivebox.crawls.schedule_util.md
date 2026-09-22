# {py:mod}`archivebox.crawls.schedule_util`

```{py:module} archivebox.crawls.schedule_util
```

```{autodoc2-docstring} archivebox.crawls.schedule_util
:allowtitles:
```

## Module Contents

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`normalize_schedule <archivebox.crawls.schedule_util.normalize_schedule>`
  - ```{autodoc2-docstring} archivebox.crawls.schedule_util.normalize_schedule
    :summary:
    ```
* - {py:obj}`validate_schedule <archivebox.crawls.schedule_util.validate_schedule>`
  - ```{autodoc2-docstring} archivebox.crawls.schedule_util.validate_schedule
    :summary:
    ```
* - {py:obj}`next_run_for_schedule <archivebox.crawls.schedule_util.next_run_for_schedule>`
  - ```{autodoc2-docstring} archivebox.crawls.schedule_util.next_run_for_schedule
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SCHEDULE_ALIASES <archivebox.crawls.schedule_util.SCHEDULE_ALIASES>`
  - ```{autodoc2-docstring} archivebox.crawls.schedule_util.SCHEDULE_ALIASES
    :summary:
    ```
````

### API

````{py:data} SCHEDULE_ALIASES
:canonical: archivebox.crawls.schedule_util.SCHEDULE_ALIASES
:type: dict[str, str]
:value: >
   None

```{autodoc2-docstring} archivebox.crawls.schedule_util.SCHEDULE_ALIASES
```

````

````{py:function} normalize_schedule(schedule: str) -> str
:canonical: archivebox.crawls.schedule_util.normalize_schedule

```{autodoc2-docstring} archivebox.crawls.schedule_util.normalize_schedule
```
````

````{py:function} validate_schedule(schedule: str) -> str
:canonical: archivebox.crawls.schedule_util.validate_schedule

```{autodoc2-docstring} archivebox.crawls.schedule_util.validate_schedule
```
````

````{py:function} next_run_for_schedule(schedule: str, after: datetime.datetime) -> datetime.datetime
:canonical: archivebox.crawls.schedule_util.next_run_for_schedule

```{autodoc2-docstring} archivebox.crawls.schedule_util.next_run_for_schedule
```
````
