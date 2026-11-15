# {py:mod}`archivebox.personas.state_forms`

```{py:module} archivebox.personas.state_forms
```

```{autodoc2-docstring} archivebox.personas.state_forms
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PersonaStateForm <archivebox.personas.state_forms.PersonaStateForm>`
  - ```{autodoc2-docstring} archivebox.personas.state_forms.PersonaStateForm
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`validate_cookies <archivebox.personas.state_forms.validate_cookies>`
  - ```{autodoc2-docstring} archivebox.personas.state_forms.validate_cookies
    :summary:
    ```
* - {py:obj}`validate_auth <archivebox.personas.state_forms.validate_auth>`
  - ```{autodoc2-docstring} archivebox.personas.state_forms.validate_auth
    :summary:
    ```
* - {py:obj}`normalized_domain <archivebox.personas.state_forms.normalized_domain>`
  - ```{autodoc2-docstring} archivebox.personas.state_forms.normalized_domain
    :summary:
    ```
* - {py:obj}`profile_directories <archivebox.personas.state_forms.profile_directories>`
  - ```{autodoc2-docstring} archivebox.personas.state_forms.profile_directories
    :summary:
    ```
* - {py:obj}`auth_domain_entries <archivebox.personas.state_forms.auth_domain_entries>`
  - ```{autodoc2-docstring} archivebox.personas.state_forms.auth_domain_entries
    :summary:
    ```
* - {py:obj}`browser_state_summary <archivebox.personas.state_forms.browser_state_summary>`
  - ```{autodoc2-docstring} archivebox.personas.state_forms.browser_state_summary
    :summary:
    ```
* - {py:obj}`remove_domain <archivebox.personas.state_forms.remove_domain>`
  - ```{autodoc2-docstring} archivebox.personas.state_forms.remove_domain
    :summary:
    ```
````

### API

````{py:function} validate_cookies(text)
:canonical: archivebox.personas.state_forms.validate_cookies

```{autodoc2-docstring} archivebox.personas.state_forms.validate_cookies
```
````

````{py:function} validate_auth(text)
:canonical: archivebox.personas.state_forms.validate_auth

```{autodoc2-docstring} archivebox.personas.state_forms.validate_auth
```
````

`````{py:class} PersonaStateForm
:canonical: archivebox.personas.state_forms.PersonaStateForm

Bases: {py:obj}`django.forms.Form`

```{autodoc2-docstring} archivebox.personas.state_forms.PersonaStateForm
```

````{py:attribute} artifact
:canonical: archivebox.personas.state_forms.PersonaStateForm.artifact
:value: >
   'ChoiceField(...)'

```{autodoc2-docstring} archivebox.personas.state_forms.PersonaStateForm.artifact
```

````

````{py:attribute} action
:canonical: archivebox.personas.state_forms.PersonaStateForm.action
:value: >
   'ChoiceField(...)'

```{autodoc2-docstring} archivebox.personas.state_forms.PersonaStateForm.action
```

````

````{py:attribute} domain
:canonical: archivebox.personas.state_forms.PersonaStateForm.domain
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.personas.state_forms.PersonaStateForm.domain
```

````

````{py:attribute} payload
:canonical: archivebox.personas.state_forms.PersonaStateForm.payload
:value: >
   'CharField(...)'

```{autodoc2-docstring} archivebox.personas.state_forms.PersonaStateForm.payload
```

````

````{py:method} clean()
:canonical: archivebox.personas.state_forms.PersonaStateForm.clean

```{autodoc2-docstring} archivebox.personas.state_forms.PersonaStateForm.clean
```

````

````{py:method} apply(persona)
:canonical: archivebox.personas.state_forms.PersonaStateForm.apply

```{autodoc2-docstring} archivebox.personas.state_forms.PersonaStateForm.apply
```

````

`````

````{py:function} normalized_domain(value)
:canonical: archivebox.personas.state_forms.normalized_domain

```{autodoc2-docstring} archivebox.personas.state_forms.normalized_domain
```
````

````{py:function} profile_directories(root)
:canonical: archivebox.personas.state_forms.profile_directories

```{autodoc2-docstring} archivebox.personas.state_forms.profile_directories
```
````

````{py:function} auth_domain_entries(payload)
:canonical: archivebox.personas.state_forms.auth_domain_entries

```{autodoc2-docstring} archivebox.personas.state_forms.auth_domain_entries
```
````

````{py:function} browser_state_summary(persona, profile_inventory=None)
:canonical: archivebox.personas.state_forms.browser_state_summary

```{autodoc2-docstring} archivebox.personas.state_forms.browser_state_summary
```
````

````{py:function} remove_domain(persona, domain)
:canonical: archivebox.personas.state_forms.remove_domain

```{autodoc2-docstring} archivebox.personas.state_forms.remove_domain
```
````
