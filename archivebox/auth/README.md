# SSO and account authentication

ArchiveBox can use django-allauth for OpenID Connect (OIDC), OAuth social login,
and SAML 2.0 service-provider login. Local username/password, LDAP, and trusted
reverse-proxy authentication remain available. ArchiveBox is a relying party,
not an OAuth authorization server or identity provider.

## Enable

Install `archivebox[allauth]` for OIDC/OAuth, or `archivebox[saml]` for SAML plus
OIDC/OAuth. Docker images include both; authentication remains disabled until
explicitly configured. In a source checkout:

```bash
uv sync --extra saml
```

Create your first administrator at `/admin/login/` before opening registration.
Set a stable HTTPS `BASE_URL`, then configure these environment variables or the
`[ALLAUTH_CONFIG]` section of your collection's `ArchiveBox.conf`:

```ini
[ALLAUTH_CONFIG]
ALLAUTH_ENABLED = True
REGISTRATION_ENABLED = False
REGISTRATION_MODE = approval
DEFAULT_USER_PERMISSIONS = none
EMAIL_VERIFICATION = none
```

With the same configuration/environment as the server, apply the additional
allauth migrations to your existing collection and restart the server:

```bash
archivebox manage migrate --noinput
# Docker Compose:
docker compose exec archivebox archivebox manage migrate --noinput
docker compose restart archivebox
```

Keep a database backup before upgrading. Existing users and password hashes are
preserved. `/admin/login/` retains username/password login and first-admin setup;
it also links to `/accounts/login/`, which lists the configured providers and
accepts username or email. Installing the extra without `ALLAUTH_ENABLED=True`
does not change routes or authentication. Disabling it restores the original
routes without deleting linked account records.

Provider settings are server configuration: restart after changing them. They
are redacted in config displays/exports and excluded from capture-hook environments.
Store them with the same permissions as other server credentials.

## OIDC: Keycloak, Authentik, Authelia, Okta, and other conforming providers

Create a confidential web client in your IdP. Configure its discovery issuer URL,
client ID, secret, and redirect URI. Example environment variable:

```bash
export SOCIALACCOUNT_PROVIDERS='{
  "openid_connect": {
    "OAUTH_PKCE_ENABLED": true,
    "APPS": [{
      "provider_id": "company",
      "name": "Company SSO",
      "client_id": "archivebox",
      "secret": "YOUR_CLIENT_SECRET",
      "settings": {
        "server_url": "https://sso.example.com/realms/company"
      }
    }]
  }
}'
```

Register exactly `https://ADMIN_HOST/accounts/oidc/company/login/callback/` at
the IdP. `ADMIN_HOST` is the host serving ArchiveBox administration, including
the port if nonstandard. With subdomain routing, use the **admin** hostname,
not the public/replay hostname. Multiple OIDC IdPs can be configured as separate
`APPS` with unique `provider_id` values. Use stable identifiers; changing one
changes which external identity is associated with existing linked accounts.

## OAuth social login

Use an allauth provider name as a key in the same `SOCIALACCOUNT_PROVIDERS`
dictionary. Only configured provider modules are loaded. For example:

```json
{
  "github": {
    "APP": {
      "client_id": "YOUR_CLIENT_ID",
      "secret": "YOUR_CLIENT_SECRET"
    }
  }
}
```

GitHub's callback is `https://ADMIN_HOST/accounts/github/login/callback/`.
Google and other providers have their own settings, scopes, and callback URLs;
see the [allauth provider documentation](https://docs.allauth.org/en/latest/socialaccount/providers/index.html).
Merge provider entries into one dictionary to offer multiple login choices.
Provider login initiation requires CSRF-protected POST confirmation. Access and
refresh tokens are not stored in the ArchiveBox database.

## SAML 2.0

Install the `saml` extra. Python wheels cover common platforms; source builds
of `xmlsec`/`lxml` require their system development libraries.

```json
{
  "saml": {
    "APPS": [{
      "provider_id": "https://sso.example.com/realms/company",
      "name": "Company SAML",
      "client_id": "company",
      "settings": {
        "idp": {
          "entity_id": "https://sso.example.com/realms/company",
          "metadata_url": "https://sso.example.com/realms/company/protocol/saml/descriptor"
        },
        "attribute_mapping": {
          "email": "email",
          "username": "username",
          "first_name": "firstName",
          "last_name": "lastName"
        },
        "advanced": {
          "want_assertion_signed": true,
          "reject_idp_initiated_sso": true,
          "reject_deprecated_algorithm": true
        }
      }
    }]
  }
}
```

Configure the IdP using ArchiveBox's metadata:

| Purpose | URL |
| --- | --- |
| SP entity ID and metadata | `https://ADMIN_HOST/accounts/saml/company/metadata/` |
| Assertion Consumer Service (HTTP POST) | `https://ADMIN_HOST/accounts/saml/company/acs/` |
| Login initiation | `https://ADMIN_HOST/accounts/saml/company/login/` |
| Single Logout Service callback | `https://ADMIN_HOST/accounts/saml/company/sls/` |

`client_id` is the URL slug; `provider_id` identifies the IdP and must remain
stable. Configure a persistent NameID, or map `uid` to an immutable IdP user
identifier. Do not use a mutable email address as the identity key. Attribute
names in the example must match your IdP's actual assertion attributes. Do not
map `email_verified` unless your IdP actually verifies ownership.

Require signed assertions in the IdP to match this example. Allauth validates
signatures, issuer, audience, destination, expiry, and the initiating request.
Unsolicited IdP-initiated login is rejected by default. Metadata may instead be
configured inline with `entity_id`, `sso_url`, `slo_url`, and `x509cert` in `idp`.
For signed requests or encrypted assertions, configure the SP certificate and
private key through allauth's `settings.advanced` options and import the resulting
metadata into the IdP. See [SAML configuration](https://docs.allauth.org/en/latest/socialaccount/providers/saml.html).

Keep HTTPS and ArchiveBox's host-only session cookies. The allauth ACS handoff
handles cross-site POSTs without broadening cookies to archived-content hosts.
Configure callbacks directly on the admin hostname; a redirect from a replay
hostname cannot preserve the SAML POST body.

## Server security modes and hostnames

| Mode | Authentication |
| --- | --- |
| `auto` | Uses the resolved mode: isolated subdomains on `.localhost`, otherwise safe single-domain replay. |
| `safe-subdomains-fullreplay` | Login and every provider callback live on `admin.*`; session, CSRF, and temporary SAML cookies stay host-only there. |
| `safe-onedomain-nojsreplay` | Login and callbacks use the configured server hostname; archived scripts remain disabled. |
| `danger-onedomain-fullreplay` | Login works on the configured hostname, with that mode's existing shared-origin risks. |
| `unsafe-onedomain-noadmin` | All login, account, callback, and admin routes remain forbidden. SSO does not bypass this mode. |

In isolated mode, `api.*` still requires API credentials. Browser SSO does not
make API requests authenticated. The only cookie shared with the public/replay
hostname family is `archivebox_admin_logged_in=1`, a UI hint that grants no
permission. Neither the admin session nor temporary provider state is shared
with `web.*`, `snap-*.*`, or original-domain replay hosts such as
`example.com.archivebox.example`. Login redirects may return to the explicitly
configured ArchiveBox hostname family, but not arbitrary external destinations.

Private replay retains its existing host-only, snapshot-scoped replay grants.
These are separate from the shared one-bit hint: they authorize reading the
granted private snapshot, never administration or API access. They contain no
admin session cookie and are checked against the live server-side login session;
local logout or password changes revoke their authority.

## Registration, permissions, and linking

- `REGISTRATION_ENABLED=False` closes both local and provider signup. Already
  linked users can still log in. To link an existing account, first log in locally
  and visit `/accounts/3rdparty/`, then explicitly connect a provider.
- `REGISTRATION_ENABLED=True` with `REGISTRATION_MODE=approval` creates inactive
  accounts. An administrator must activate them in `/admin/auth/user/` before
  they can log in. This policy also covers automatic provider signup.
- `REGISTRATION_MODE=open` activates new accounts immediately. There is no
  invitation workflow; the previous PR's misleading `invite` option is rejected.
- `DEFAULT_USER_PERMISSIONS=none` leaves staff and superuser privileges unset.
  `admin` grants full ArchiveBox administration to every new account. Combine
  this with approval, or restrict enrollment at a trusted IdP. This setting
  does not change existing users or map IdP groups to roles.
- A matching email does not link accounts by default. Account linking requires
  an authenticated user's explicit action. To deliberately trust provider-verified
  email for login to existing accounts, enable `SOCIALACCOUNT_EMAIL_AUTHENTICATION`.
  Add `SOCIALACCOUNT_EMAIL_AUTO_CONNECT=True` only if you also want to persist
  that association. Unverified provider emails cannot authorize this matching.
  These options grant configured trusted providers authority over local accounts.

For email confirmation and password reset, configure `EMAIL_HOST`, `EMAIL_PORT`
(default 587), `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL`.
TLS is enabled by default; for implicit TLS use `EMAIL_USE_SSL=True` and
`EMAIL_USE_TLS=False`. Without `EMAIL_HOST`, mail is printed to the server console
for development. Set `EMAIL_VERIFICATION=mandatory` when local email ownership
must be confirmed. Provider email verification follows allauth's provider rules.

Logout clears the local ArchiveBox session and requires POST. It does **not**
automatically terminate every IdP session. SAML's SLS callback is exposed, but
SP-initiated global logout and OIDC back-channel logout are not implemented here.
An existing IdP session may therefore sign the user back in without another
password prompt. `LOGOUT_REDIRECT_URL` can send users to a deployment-specific
logout landing page.

## Verification

```bash
uv sync --dev --extra saml
uv run --extra saml pytest archivebox/tests/test_allauth_config.py archivebox/tests/test_allauth_integration.py
# Requires Docker and the normal ArchiveBox Chrome installation:
uv run --extra saml pytest archivebox/tests/test_allauth_providers.py
```

Provider acceptance uses a real Keycloak container, signed SAML assertions,
OIDC authorization-code exchange with PKCE, and Chromium. It covers approval,
closed registration, explicit account linking, account collisions, cookie isolation, logout, invalid state,
replayed assertions, and altered signatures. OAuth providers other than OIDC use
allauth's upstream integrations; each deployment still needs its provider's
credentials and callback configuration.
