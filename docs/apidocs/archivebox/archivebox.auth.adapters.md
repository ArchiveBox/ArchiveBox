# {py:mod}`archivebox.auth.adapters`

```{py:module} archivebox.auth.adapters
```

```{autodoc2-docstring} archivebox.auth.adapters
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ArchiveBoxAccountAdapter <archivebox.auth.adapters.ArchiveBoxAccountAdapter>`
  - ```{autodoc2-docstring} archivebox.auth.adapters.ArchiveBoxAccountAdapter
    :summary:
    ```
* - {py:obj}`ArchiveBoxSocialAccountAdapter <archivebox.auth.adapters.ArchiveBoxSocialAccountAdapter>`
  - ```{autodoc2-docstring} archivebox.auth.adapters.ArchiveBoxSocialAccountAdapter
    :summary:
    ```
````

### API

`````{py:class} ArchiveBoxAccountAdapter
:canonical: archivebox.auth.adapters.ArchiveBoxAccountAdapter

Bases: {py:obj}`allauth.account.adapter.DefaultAccountAdapter`

```{autodoc2-docstring} archivebox.auth.adapters.ArchiveBoxAccountAdapter
```

````{py:method} is_safe_url(url)
:canonical: archivebox.auth.adapters.ArchiveBoxAccountAdapter.is_safe_url

```{autodoc2-docstring} archivebox.auth.adapters.ArchiveBoxAccountAdapter.is_safe_url
```

````

````{py:method} new_user(request)
:canonical: archivebox.auth.adapters.ArchiveBoxAccountAdapter.new_user

```{autodoc2-docstring} archivebox.auth.adapters.ArchiveBoxAccountAdapter.new_user
```

````

`````

`````{py:class} ArchiveBoxSocialAccountAdapter
:canonical: archivebox.auth.adapters.ArchiveBoxSocialAccountAdapter

Bases: {py:obj}`allauth.socialaccount.adapter.DefaultSocialAccountAdapter`

```{autodoc2-docstring} archivebox.auth.adapters.ArchiveBoxSocialAccountAdapter
```

````{py:method} is_open_for_signup(request, sociallogin)
:canonical: archivebox.auth.adapters.ArchiveBoxSocialAccountAdapter.is_open_for_signup

```{autodoc2-docstring} archivebox.auth.adapters.ArchiveBoxSocialAccountAdapter.is_open_for_signup
```

````

`````
