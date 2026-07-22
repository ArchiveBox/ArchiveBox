# {py:mod}`archivebox.core.middleware`

```{py:module} archivebox.core.middleware
```

```{autodoc2-docstring} archivebox.core.middleware
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ReverseProxyAuthMiddleware <archivebox.core.middleware.ReverseProxyAuthMiddleware>`
  -
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_admin_login_hint_cookie_domain <archivebox.core.middleware._admin_login_hint_cookie_domain>`
  - ```{autodoc2-docstring} archivebox.core.middleware._admin_login_hint_cookie_domain
    :summary:
    ```
* - {py:obj}`detect_timezone <archivebox.core.middleware.detect_timezone>`
  - ```{autodoc2-docstring} archivebox.core.middleware.detect_timezone
    :summary:
    ```
* - {py:obj}`TimezoneMiddleware <archivebox.core.middleware.TimezoneMiddleware>`
  - ```{autodoc2-docstring} archivebox.core.middleware.TimezoneMiddleware
    :summary:
    ```
* - {py:obj}`AdminCookieIsolationMiddleware <archivebox.core.middleware.AdminCookieIsolationMiddleware>`
  - ```{autodoc2-docstring} archivebox.core.middleware.AdminCookieIsolationMiddleware
    :summary:
    ```
* - {py:obj}`CacheControlMiddleware <archivebox.core.middleware.CacheControlMiddleware>`
  - ```{autodoc2-docstring} archivebox.core.middleware.CacheControlMiddleware
    :summary:
    ```
* - {py:obj}`ServerSecurityModeMiddleware <archivebox.core.middleware.ServerSecurityModeMiddleware>`
  - ```{autodoc2-docstring} archivebox.core.middleware.ServerSecurityModeMiddleware
    :summary:
    ```
* - {py:obj}`HostRoutingMiddleware <archivebox.core.middleware.HostRoutingMiddleware>`
  - ```{autodoc2-docstring} archivebox.core.middleware.HostRoutingMiddleware
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ADMIN_LOGIN_HINT_COOKIE <archivebox.core.middleware.ADMIN_LOGIN_HINT_COOKIE>`
  - ```{autodoc2-docstring} archivebox.core.middleware.ADMIN_LOGIN_HINT_COOKIE
    :summary:
    ```
````

### API

````{py:data} ADMIN_LOGIN_HINT_COOKIE
:canonical: archivebox.core.middleware.ADMIN_LOGIN_HINT_COOKIE
:value: >
   'archivebox_admin_logged_in'

```{autodoc2-docstring} archivebox.core.middleware.ADMIN_LOGIN_HINT_COOKIE
```

````

````{py:function} _admin_login_hint_cookie_domain(config) -> str | None
:canonical: archivebox.core.middleware._admin_login_hint_cookie_domain

```{autodoc2-docstring} archivebox.core.middleware._admin_login_hint_cookie_domain
```
````

````{py:function} detect_timezone(request, activate: bool = True)
:canonical: archivebox.core.middleware.detect_timezone

```{autodoc2-docstring} archivebox.core.middleware.detect_timezone
```
````

````{py:function} TimezoneMiddleware(get_response)
:canonical: archivebox.core.middleware.TimezoneMiddleware

```{autodoc2-docstring} archivebox.core.middleware.TimezoneMiddleware
```
````

````{py:function} AdminCookieIsolationMiddleware(get_response)
:canonical: archivebox.core.middleware.AdminCookieIsolationMiddleware

```{autodoc2-docstring} archivebox.core.middleware.AdminCookieIsolationMiddleware
```
````

````{py:function} CacheControlMiddleware(get_response)
:canonical: archivebox.core.middleware.CacheControlMiddleware

```{autodoc2-docstring} archivebox.core.middleware.CacheControlMiddleware
```
````

````{py:function} ServerSecurityModeMiddleware(get_response)
:canonical: archivebox.core.middleware.ServerSecurityModeMiddleware

```{autodoc2-docstring} archivebox.core.middleware.ServerSecurityModeMiddleware
```
````

````{py:function} HostRoutingMiddleware(get_response)
:canonical: archivebox.core.middleware.HostRoutingMiddleware

```{autodoc2-docstring} archivebox.core.middleware.HostRoutingMiddleware
```
````

`````{py:class} ReverseProxyAuthMiddleware(get_response)
:canonical: archivebox.core.middleware.ReverseProxyAuthMiddleware

Bases: {py:obj}`django.contrib.auth.middleware.RemoteUserMiddleware`

````{py:attribute} header
:canonical: archivebox.core.middleware.ReverseProxyAuthMiddleware.header
:value: >
   'HTTP_REMOTE_USER'

```{autodoc2-docstring} archivebox.core.middleware.ReverseProxyAuthMiddleware.header
```

````

````{py:method} process_request(request)
:canonical: archivebox.core.middleware.ReverseProxyAuthMiddleware.process_request

```{autodoc2-docstring} archivebox.core.middleware.ReverseProxyAuthMiddleware.process_request
```

````

`````
