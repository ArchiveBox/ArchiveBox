# {py:mod}`archivebox.search.admin`

```{py:module} archivebox.search.admin
```

```{autodoc2-docstring} archivebox.search.admin
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SearchResultsChangeList <archivebox.search.admin.SearchResultsChangeList>`
  - ```{autodoc2-docstring} archivebox.search.admin.SearchResultsChangeList
    :summary:
    ```
* - {py:obj}`SearchResultsAdminMixin <archivebox.search.admin.SearchResultsAdminMixin>`
  - ```{autodoc2-docstring} archivebox.search.admin.SearchResultsAdminMixin
    :summary:
    ```
````

### API

`````{py:class} SearchResultsChangeList(request, *args, **kwargs)
:canonical: archivebox.search.admin.SearchResultsChangeList

Bases: {py:obj}`django.contrib.admin.views.main.ChangeList`

```{autodoc2-docstring} archivebox.search.admin.SearchResultsChangeList
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.search.admin.SearchResultsChangeList.__init__
```

````{py:method} get_results(request)
:canonical: archivebox.search.admin.SearchResultsChangeList.get_results

```{autodoc2-docstring} archivebox.search.admin.SearchResultsChangeList.get_results
```

````

````{py:method} get_filters_params(params=None)
:canonical: archivebox.search.admin.SearchResultsChangeList.get_filters_params

```{autodoc2-docstring} archivebox.search.admin.SearchResultsChangeList.get_filters_params
```

````

`````

`````{py:class} SearchResultsAdminMixin(model, admin_site)
:canonical: archivebox.search.admin.SearchResultsAdminMixin

Bases: {py:obj}`django.contrib.admin.ModelAdmin`

```{autodoc2-docstring} archivebox.search.admin.SearchResultsAdminMixin
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.search.admin.SearchResultsAdminMixin.__init__
```

````{py:attribute} show_search_mode_selector
:canonical: archivebox.search.admin.SearchResultsAdminMixin.show_search_mode_selector
:value: >
   True

```{autodoc2-docstring} archivebox.search.admin.SearchResultsAdminMixin.show_search_mode_selector
```

````

````{py:method} get_changelist(request, **kwargs)
:canonical: archivebox.search.admin.SearchResultsAdminMixin.get_changelist

```{autodoc2-docstring} archivebox.search.admin.SearchResultsAdminMixin.get_changelist
```

````

````{py:method} get_default_search_mode()
:canonical: archivebox.search.admin.SearchResultsAdminMixin.get_default_search_mode

```{autodoc2-docstring} archivebox.search.admin.SearchResultsAdminMixin.get_default_search_mode
```

````

````{py:method} get_search_mode_options()
:canonical: archivebox.search.admin.SearchResultsAdminMixin.get_search_mode_options

```{autodoc2-docstring} archivebox.search.admin.SearchResultsAdminMixin.get_search_mode_options
```

````

````{py:method} get_search_results(request, queryset, search_term: str)
:canonical: archivebox.search.admin.SearchResultsAdminMixin.get_search_results

```{autodoc2-docstring} archivebox.search.admin.SearchResultsAdminMixin.get_search_results
```

````

`````
