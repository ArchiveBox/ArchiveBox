# {py:mod}`archivebox.core.admin_users`

```{py:module} archivebox.core.admin_users
```

```{autodoc2-docstring} archivebox.core.admin_users
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CustomUserAdmin <archivebox.core.admin_users.CustomUserAdmin>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`register_admin <archivebox.core.admin_users.register_admin>`
  - ```{autodoc2-docstring} archivebox.core.admin_users.register_admin
    :summary:
    ```
````

### API

`````{py:class} CustomUserAdmin(model, admin_site)
:canonical: archivebox.core.admin_users.CustomUserAdmin

Bases: {py:obj}`django.contrib.auth.admin.UserAdmin`

````{py:attribute} sort_fields
:canonical: archivebox.core.admin_users.CustomUserAdmin.sort_fields
:value: >
   ['id', 'email', 'username', 'is_superuser', 'last_login', 'date_joined']

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.sort_fields
```

````

````{py:attribute} list_display
:canonical: archivebox.core.admin_users.CustomUserAdmin.list_display
:value: >
   ['username', 'id', 'email', 'is_superuser', 'last_login', 'date_joined']

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.list_display
```

````

````{py:attribute} readonly_fields
:canonical: archivebox.core.admin_users.CustomUserAdmin.readonly_fields
:value: >
   ('snapshot_set', 'archiveresult_set', 'tag_set', 'apitoken_set', 'outboundwebhook_set')

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.readonly_fields
```

````

````{py:attribute} change_form_template
:canonical: archivebox.core.admin_users.CustomUserAdmin.change_form_template
:value: >
   'admin/auth/user/change_form.html'

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.change_form_template
```

````

````{py:attribute} add_fieldsets
:canonical: archivebox.core.admin_users.CustomUserAdmin.add_fieldsets
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.add_fieldsets
```

````

````{py:attribute} fieldsets
:canonical: archivebox.core.admin_users.CustomUserAdmin.fieldsets
:value: >
   None

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.fieldsets
```

````

````{py:method} get_queryset(request)
:canonical: archivebox.core.admin_users.CustomUserAdmin.get_queryset

````

````{py:method} snapshot_rss_badge(obj, api_token: str = '')
:canonical: archivebox.core.admin_users.CustomUserAdmin.snapshot_rss_badge

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.snapshot_rss_badge
```

````

````{py:method} snapshot_count_badge(obj)
:canonical: archivebox.core.admin_users.CustomUserAdmin.snapshot_count_badge

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.snapshot_count_badge
```

````

````{py:method} snapshot_count_column(obj)
:canonical: archivebox.core.admin_users.CustomUserAdmin.snapshot_count_column

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.snapshot_count_column
```

````

````{py:method} get_list_display(request)
:canonical: archivebox.core.admin_users.CustomUserAdmin.get_list_display

````

````{py:method} snapshot_set(obj)
:canonical: archivebox.core.admin_users.CustomUserAdmin.snapshot_set

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.snapshot_set
```

````

````{py:method} archiveresult_set(obj)
:canonical: archivebox.core.admin_users.CustomUserAdmin.archiveresult_set

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.archiveresult_set
```

````

````{py:method} tag_set(obj)
:canonical: archivebox.core.admin_users.CustomUserAdmin.tag_set

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.tag_set
```

````

````{py:method} apitoken_set(obj)
:canonical: archivebox.core.admin_users.CustomUserAdmin.apitoken_set

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.apitoken_set
```

````

````{py:method} outboundwebhook_set(obj)
:canonical: archivebox.core.admin_users.CustomUserAdmin.outboundwebhook_set

```{autodoc2-docstring} archivebox.core.admin_users.CustomUserAdmin.outboundwebhook_set
```

````

`````

````{py:function} register_admin(admin_site)
:canonical: archivebox.core.admin_users.register_admin

```{autodoc2-docstring} archivebox.core.admin_users.register_admin
```
````
