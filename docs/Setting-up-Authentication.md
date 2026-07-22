# Setting Up Authentication

> *💬 We offer [consulting services](https://docs.monadical.com/s/archivebox-consulting-services) to set up, integrate, and maintain ArchiveBox with your org's auth & hosting.  
> If you need support, advanced development to capture difficult sites, audit logging, and more, we can provide it!*  
> <sub>We use this revenue (from corporate clients who can afford to pay) to support open source development and keep ArchiveBox free.</sub>

---

ArchiveBox supports several types of authentication for users logging in via the Admin Web UI or REST API.

## Set Up Admin Web UI Permissions

<img src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/024913f0-ad2c-463c-aa4a-eb3d0ec8eb64" alt="Non-admin user permissions are only available to paying ArchiveBox clients" width="200px" align="right">

Use these options to set up your desired permissions for non-admin guest users:
- [`PUBLIC_INDEX=True`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#public_index): Default *allows* non-logged-in users to see Snapshot list
- [`PUBLIC_ADD_VIEW=False`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#public_add_view): Default *doesn't allow* non-logged-in users to submit new URLs
- [`PERMISSIONS=public`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#permissions): Default *allows* non-logged-in users to see Snapshot content (set to `unlisted` or `private` to gate it; replaces the removed legacy `PUBLIC_SNAPSHOTS` toggle, which was a global on/off — `PERMISSIONS` is now per-Snapshot)

> [!NOTE]
> **Open source ArchiveBox does not support setting up *non-admin* users** & groups with custom permissions. We do offer this feature, audit logging, and more to [paying clients](https://docs.monadical.com/s/archivebox-consulting-services).

- [Wiki: Configuration](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#permissions) (`PUBLIC_INDEX`, `PUBLIC_ADD_VIEW`, `PERMISSIONS`)
- [Wiki: Security Overview](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview)

<br/>
<br/>

## Admin Web UI Authentication Methods


<br/>

### Username & Password (the default)

You need a user account to access the Admin UI, you can run the commands below to create/edit a user from the CLI:

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
DJANGO_SUPERUSER_PASSWORD=archivebox-docs-password uv run --project "$project_dir" --no-sync archivebox manage createsuperuser --noinput --username archivebox-docs --email docs@example.com
uv run --project "$project_dir" --no-sync archivebox manage shell -c "from django.contrib.auth import get_user_model; user=get_user_model().objects.get(username='archivebox-docs'); user.set_password('archivebox-docs-new-password'); user.save()"
uv run --project "$project_dir" --no-sync archivebox manage shell -c "from django.contrib.auth import authenticate; assert authenticate(username='archivebox-docs', password='archivebox-docs-new-password') is not None"
```

> [!TIP]
> If using Docker, you can set [`ADMIN_USERNAME` & `ADMIN_PASSWORD`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#admin_username--admin_password) to auto-create an admin account on first run.

Existing users can be managed from the Admin UI here: [`/admin/auth/user/`](http://127.0.0.1:8000/admin/auth/user/),  
and you can change your password in the UI here: [`/admin/password_change/`](http://127.0.0.1:8000/admin/password_change/).

<br/>
<br/>

### Reverse Proxy Authentication

> Can be used with a reverse proxy auth provider like [oauth2-proxy](https://github.com/oauth2-proxy/oauth2-proxy), [Cloudflare Zero Trust](https://developers.cloudflare.com/cloudflare-one/tutorials/access-workers/#create-a-worker-with-custom-headers), [Authentik](https://docs.goauthentik.io/docs/providers/proxy/), and others.

Set these ArchiveBox configuration values based on your reverse proxy setup and needs:
```bash
# REQUIRED: the header where your upstream reverse proxy will place the authenticated user's username/email
# EXAMPLE: Cf-Access-Authenticated-User-Email (if using Cloudflare Access / Zero Trust)
set -euo pipefail; export REVERSE_PROXY_USER_HEADER=X-Remote-User

# REQUIRED: the IP/CIDR of your upstream reverse proxy server
# WARNING: make sure this range contains ONLY your reverse proxy server!
# ArchiveBox will completely trust any IP in this range for authentication
export REVERSE_PROXY_WHITELIST=192.0.2.3/32

# OPTIONAL: redirect users to an external URL after they log out
export LOGOUT_REDIRECT_URL=https://auth.yourcompany.example.com/after/logout
test "$REVERSE_PROXY_USER_HEADER" = X-Remote-User
test "$REVERSE_PROXY_WHITELIST" = 192.0.2.3/32
test "$LOGOUT_REDIRECT_URL" = https://auth.yourcompany.example.com/after/logout
```

- https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#reverse_proxy_user_header
- https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#reverse_proxy_whitelist
- https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#logout_redirect_url
- https://github.com/ArchiveBox/ArchiveBox/pull/866

<br/>

### LDAP Authentication

> Can be used with an SSO provider like [Authentik](https://github.com/goauthentik/authentik), [Authelia](https://github.com/authelia/authelia), [Okta / Auth0](https://www.okta.com/), [Keycloak](https://www.keycloak.org/), and others.

First, install the `ldap` add-on to use this feature (not needed for Docker Archivebox).
```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; tool_root="$(mktemp -d)"; UV_TOOL_DIR="$tool_root/tools" UV_TOOL_BIN_DIR="$tool_root/bin" uv tool install --python 3.13 --upgrade "$project_dir[ldap]"; "$tool_root/bin/archivebox" --help
```

Then set these configuration values to finish configuring LDAP:
```bash
set -euo pipefail; export LDAP_ENABLED=True
export LDAP_SERVER_URI="ldap://ldap.example.com:3389"
export LDAP_BIND_DN="ou=archivebox,ou=services,dc=ldap.example.com"
export LDAP_BIND_PASSWORD="secret-bind-user-password"
export LDAP_USER_BASE="ou=users,ou=archivebox,ou=services,dc=ldap.example.com"
export LDAP_USER_FILTER="(objectClass=user)"
export LDAP_USERNAME_ATTR="uid"
export LDAP_FIRSTNAME_ATTR="givenName"
export LDAP_LASTNAME_ATTR="sn"
export LDAP_EMAIL_ATTR="mail"
test "$LDAP_ENABLED" = True; test "$LDAP_USERNAME_ATTR" = uid; test "$LDAP_EMAIL_ATTR" = mail
```

- https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#ldap
- https://github.com/ArchiveBox/ArchiveBox/pull/1214
- https://github.com/django-auth-ldap/django-auth-ldap#example-configuration
- https://jumpcloud.com/blog/what-is-ldap-authentication

<br/>

### Not Yet Supported: SAML / OAuth2 / OpenID Authentication

> *We'd welcome PRs to add support for these using `django-allauth`!*

These methods are not natively supported by ArchiveBox at the moment. However it is still possible to use them with ArchiveBox by running your own [IdP (Identity Provider)](https://www.cloudflare.com/learning/access-management/what-is-an-identity-provider/) server to act as a bridge (e.g. [Authentik](https://docs.goauthentik.io/docs/providers/saml/), [Authelia](https://www.authelia.com/configuration/identity-providers/introduction/#openid-connect-10), [oauth2-proxy](https://github.com/oauth2-proxy/oauth2-proxy)).

The IdP server can act as a middleman gateway to authenticate users using an external SAML/OAuth/OpenID/etc. provider (e.g. Google, Microsoft, Github, Facebook, etc.), and then pass on the authenticated user's session info to ArchiveBox using LDAP or reverse proxy headers (as described above).

- https://www.cloudflare.com/learning/access-management/what-is-saml/
- https://docs.goauthentik.io/docs/providers/saml/
- https://docs.goauthentik.io/docs/providers/oauth2/
- https://www.authelia.com/configuration/identity-providers/introduction/#openid-connect-10
- https://github.com/oauth2-proxy/oauth2-proxy
- https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview

<br/>

---

<br/>

## REST API

The REST API (available starting in v0.8.0) supports several methods of authentication for convenience.  
  
To see API docs, try endpoints interactively, and see how auth works, visit this URL on your ArchiveBox server:  
[`http://127.0.0.1:8000/api/v1/docs`](http://127.0.0.1:8000/api/v1/docs)

<img width="500" alt="Screenshot of django-ninja Swagger API docs page" src="https://github.com/ArchiveBox/ArchiveBox/assets/511499/ad914143-f48b-4d4e-aa8c-f89a2c70cee7">

<br/><br/>

To get started using the REST API, you can generate an API key for your user in the Admin Web UI:  
[`http://127.0.0.1:8000/admin/api/apitoken/add/`](http://127.0.0.1:8000/admin/api/apitoken/add/)  
  
or by calling the `http://127.0.0.1:8000/api/v1/auth/get_api_token` endpoint with a username & password:
```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; port="${ARCHIVEBOX_DOCS_ARCHIVEBOX_PORT:-18000}"; cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox server --daemonize "127.0.0.1:$port"; server_pid="$(uv run --project "$project_dir" --no-sync archivebox manage shell -c "from archivebox.machine.models import Process; print(Process.objects.filter(process_type='server', status='running').order_by('-started_at').values_list('pid', flat=True).first() or '')")"; test -n "$server_pid"; trap 'kill "$server_pid" 2>/dev/null || true' EXIT
status="$(curl -sS -o response.json -w '%{http_code}' -X POST "http://127.0.0.1:$port/api/v1/auth/get_api_token" -H 'Content-Type: application/json' -d '{"username":"missing-user","password":"wrong-password"}')"
test -s response.json; test "$status" -ge 400 || grep -q '"success": false' response.json
```

<br/>

> [!TIP]
> Bearer Tokens are the recommended method for the best balance of security and convenience.


### API Bearer Token Authentication

Pass `Authorization=Bearer YOURAPITOKENHERE` as a request header.

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; port="${ARCHIVEBOX_DOCS_ARCHIVEBOX_PORT:-18000}"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox server --daemonize "127.0.0.1:$port"; server_pid="$(uv run --project "$project_dir" --no-sync archivebox manage shell -c "from archivebox.machine.models import Process; print(Process.objects.filter(process_type='server', status='running').order_by('-started_at').values_list('pid', flat=True).first() or '')")"; test -n "$server_pid"; trap 'kill "$server_pid" 2>/dev/null || true' EXIT
status="$(curl -sS -o response.json -w '%{http_code}' "http://127.0.0.1:$port/api/v1/core/snapshots?limit=10" -H 'accept: application/json' -H 'Authorization: Bearer invalid-docs-token')"
test "$status" -ge 400; test -s response.json
```

### API Request Header Authentication

> This method is provided in case you have a reverse proxy in front of ArchiveBox that consumes the bearer header.

Pass `X-ArchiveBox-API-Key=YOURAPITOKENHERE` as a request header.

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; port="${ARCHIVEBOX_DOCS_ARCHIVEBOX_PORT:-18000}"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox server --daemonize "127.0.0.1:$port"; server_pid="$(uv run --project "$project_dir" --no-sync archivebox manage shell -c "from archivebox.machine.models import Process; print(Process.objects.filter(process_type='server', status='running').order_by('-started_at').values_list('pid', flat=True).first() or '')")"; test -n "$server_pid"; trap 'kill "$server_pid" 2>/dev/null || true' EXIT
status="$(curl -sS -o response.json -w '%{http_code}' "http://127.0.0.1:$port/api/v1/core/snapshots?limit=10" -H 'accept: application/json' -H 'X-ArchiveBox-API-Key: invalid-docs-token')"
test "$status" -ge 400; test -s response.json
```

<br/>

### API Query Parameter Authentication

> [!WARNING]
> This method is sometimes known as ["Capability URLs"](https://w3ctag.github.io/capability-urls/) because anyone in possession of the URL can perform API actions. It comes with [important security caveats](https://security.stackexchange.com/questions/118975/is-it-safe-to-include-an-api-key-in-a-requests-url) and is not recommended unless you fully understand the risks.

Pass `api_key=YOURAPITOKENHERE` as a GET/POST query parameter.

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; port="${ARCHIVEBOX_DOCS_ARCHIVEBOX_PORT:-18000}"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox server --daemonize "127.0.0.1:$port"; server_pid="$(uv run --project "$project_dir" --no-sync archivebox manage shell -c "from archivebox.machine.models import Process; print(Process.objects.filter(process_type='server', status='running').order_by('-started_at').values_list('pid', flat=True).first() or '')")"; test -n "$server_pid"; trap 'kill "$server_pid" 2>/dev/null || true' EXIT
status="$(curl -sS -o response.json -w '%{http_code}' "http://127.0.0.1:$port/api/v1/core/snapshots?limit=10&api_key=invalid-docs-token" -H 'accept: application/json')"
test "$status" -ge 400; test -s response.json
```

<br/>

### API Session Cookie Authentication

> [!CAUTION]
> We recommend sticking to header-based authentication and not using this method unless you deeply understand the CSRF/CORS security risks.
> This method is mostly useful when accessing the API from external apps where CSRF/CORS is not a concern (e.g. `curl`, mobile apps, other servers, etc.).

> Browsers enforce that requests made to the ArchiveBox API from *other origins* will not include any session cookies by default. This is is a [foundational security principle of the web](https://docs.djangoproject.com/en/5.0/ref/csrf/) that protects you from API requests being initiated by JS on websites you don't control (aka CSRF/CORS attacks).
>
> To allow incoming POST/PUT/DELETE requests from other domains **that you trust**, set [`BASE_URL`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#base_url) to the public URL of your instance — ArchiveBox derives Django's `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` from `BASE_URL` + [`SERVER_SECURITY_MODE`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#server_security_mode) automatically, including widening them to admit the admin/web/api subdomains. If your setup needs something the auto-derivation doesn't cover, [open an issue](https://github.com/ArchiveBox/ArchiveBox/issues/new/choose).

Log in via the Admin Web UI: `/admin/login/`, you can then re-use your login session id (stored in the `sessionid` cookie) for REST API requests. By default, this only allows you to make requests from the same domain ArchiveBox is being served on (e.g. from browser devtools open on an ArchiveBox page or CLI tools).

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; port="${ARCHIVEBOX_DOCS_ARCHIVEBOX_PORT:-18000}"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox server --daemonize "127.0.0.1:$port"; server_pid="$(uv run --project "$project_dir" --no-sync archivebox manage shell -c "from archivebox.machine.models import Process; print(Process.objects.filter(process_type='server', status='running').order_by('-started_at').values_list('pid', flat=True).first() or '')")"; test -n "$server_pid"; trap 'kill "$server_pid" 2>/dev/null || true' EXIT
status="$(curl -sS -o response.json -w '%{http_code}' "http://127.0.0.1:$port/api/v1/core/snapshots?limit=10" -H 'accept: application/json' -H 'Cookie: sessionid=invalid-docs-session')"
test "$status" -ge 400; test -s response.json
```

<br/>

### API HTTP Basic Authentication

> [!CAUTION]
> This method is fairly uncommon and is only useful in a few niche situations where the other methods are not available.  
> **We will likely remove this method in a future ArchiveBox release if nobody uses it.**  
> *If you rely on this method and want us to keep it, please [open an issue](https://github.com/ArchiveBox/ArchiveBox/issues/new/choose) and explain your use-case!* 

Pass your ArchiveBox admin username & password via HTTP Basic Authentication.

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; port="${ARCHIVEBOX_DOCS_ARCHIVEBOX_PORT:-18000}"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox server --daemonize "127.0.0.1:$port"; server_pid="$(uv run --project "$project_dir" --no-sync archivebox manage shell -c "from archivebox.machine.models import Process; print(Process.objects.filter(process_type='server', status='running').order_by('-started_at').values_list('pid', flat=True).first() or '')")"; test -n "$server_pid"; trap 'kill "$server_pid" 2>/dev/null || true' EXIT
status="$(curl -sS -o response.json -w '%{http_code}' "http://127.0.0.1:$port/api/v1/core/snapshots?limit=10" -u 'missing-user:wrong-password' -H 'accept: application/json')"
test "$status" -ge 400; test -s response.json
```

<br/>

#### Further Reading

- The ArchiveBox API auth implementation: [`archivebox/api/auth.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/api/auth.py#:~:text=API_AUTH_METHODS) + [`archivebox/api/v1_auth.py`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/api/v1_auth.py)
- The [`django-ninja` auth documentation](https://django-ninja.dev/guides/authentication/) (which powers our API)
- The [Swagger auth documentation](https://swagger.io/docs/specification/authentication/) for the interactive API Docs UI
