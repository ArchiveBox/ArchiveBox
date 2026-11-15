# {py:mod}`archivebox.domains.forms`

```{py:module} archivebox.domains.forms
```

```{autodoc2-docstring} archivebox.domains.forms
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DomainCrawlForm <archivebox.domains.forms.DomainCrawlForm>`
  - ```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm
    :summary:
    ```
````

### API

`````{py:class} DomainCrawlForm(*args, **kwargs)
:canonical: archivebox.domains.forms.DomainCrawlForm

Bases: {py:obj}`django.forms.Form`

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm
```

```{rubric} Initialization
```

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.__init__
```

````{py:attribute} url
:canonical: archivebox.domains.forms.DomainCrawlForm.url
:value: >
   'URLField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.url
```

````

````{py:attribute} include_subdomains
:canonical: archivebox.domains.forms.DomainCrawlForm.include_subdomains
:value: >
   'BooleanField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.include_subdomains
```

````

````{py:attribute} max_depth
:canonical: archivebox.domains.forms.DomainCrawlForm.max_depth
:value: >
   'IntegerField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.max_depth
```

````

````{py:attribute} max_urls
:canonical: archivebox.domains.forms.DomainCrawlForm.max_urls
:value: >
   'IntegerField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.max_urls
```

````

````{py:attribute} concurrency
:canonical: archivebox.domains.forms.DomainCrawlForm.concurrency
:value: >
   'IntegerField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.concurrency
```

````

````{py:attribute} timeout_minutes
:canonical: archivebox.domains.forms.DomainCrawlForm.timeout_minutes
:value: >
   'IntegerField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.timeout_minutes
```

````

````{py:attribute} schedule
:canonical: archivebox.domains.forms.DomainCrawlForm.schedule
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.schedule
```

````

````{py:attribute} persona
:canonical: archivebox.domains.forms.DomainCrawlForm.persona
:value: >
   'ModelChoiceField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.persona
```

````

````{py:attribute} url_filters
:canonical: archivebox.domains.forms.DomainCrawlForm.url_filters
:value: >
   'Field(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.url_filters
```

````

````{py:attribute} tags
:canonical: archivebox.domains.forms.DomainCrawlForm.tags
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.tags
```

````

````{py:attribute} permissions
:canonical: archivebox.domains.forms.DomainCrawlForm.permissions
:value: >
   'ChoiceField(...)'

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.permissions
```

````

````{py:method} clean_url()
:canonical: archivebox.domains.forms.DomainCrawlForm.clean_url

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.clean_url
```

````

````{py:method} clean_url_filters()
:canonical: archivebox.domains.forms.DomainCrawlForm.clean_url_filters

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.clean_url_filters
```

````

````{py:method} clean_schedule()
:canonical: archivebox.domains.forms.DomainCrawlForm.clean_schedule

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.clean_schedule
```

````

````{py:method} clean()
:canonical: archivebox.domains.forms.DomainCrawlForm.clean

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.clean
```

````

````{py:method} save(user)
:canonical: archivebox.domains.forms.DomainCrawlForm.save

```{autodoc2-docstring} archivebox.domains.forms.DomainCrawlForm.save
```

````

`````
