# Security Policy

---

## Security Documentation

Please start by reading these links to understand our existing security model, known issues, API surfaces, and setup steps:

- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview
- https://github.com/ArchiveBox/ArchiveBox/security/advisories/
- https://github.com/ArchiveBox/ArchiveBox/tree/v0.7.4#security-risks-of-viewing-archived-js
- https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive#security-concerns
- https://github.com/ArchiveBox/ArchiveBox/wiki/Setting-up-Authentication
- https://github.com/ArchiveBox/ArchiveBox#archive-layout
- https://github.com/ArchiveBox/ArchiveBox#archivebox-development
- https://github.com/ArchiveBox/ArchiveBox/wiki/Upgrading-or-Merging-Archives
- https://github.com/ArchiveBox/ArchiveBox/wiki/Troubleshooting

---

## Reporting a Vulnerability

We use Github's built-in [Private Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) feature to accept vulnerability reports.

1. Go to the Security tab on our Github repo: https://github.com/ArchiveBox/ArchiveBox/security

2. Click the ["Report a Vulnerability"](https://github.com/ArchiveBox/ArchiveBox/security/advisories/new) button

3. Fill out the form to submit the details of the report and it will be securely sent to the maintainers

You can also contact the maintainers via our public [Zulip Chat Server zulip.archivebox.io](https://zulip.archivebox.io) or [Twitter DMs @ArchiveBoxApp](https://twitter.com/ArchiveBoxApp).

---

## CVEs and Report Credits

> [!IMPORTANT]
> **Reports that only affect `dev` or beta versions will be converted to normal Github issues and will not be issued CVEs.**  
> Reporters **will still receive credit in release notes** however.

> [!TIP]
> Reports that affect **stable published versions will be issued CVEs** and published w/ full credit.

Please read our existing published [security advisories](https://github.com/ArchiveBox/ArchiveBox/security/advisories), [Security Overview Docs](https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview), and [issues](https://github.com/ArchiveBox/ArchiveBox/issues) and avoid creating duplicates.

---

## Threat Model

### All admin users are assumed to be trusted

ArchiveBox does not support granular user permissions, there are only two types of users available in the Admin UI & REST API:

- logged in admin superusers (which are assumed to have `root` on the ArchiveBox host machine already)
- non-logged in anonymous guest users

Because admin / REST API / CLI / Python API users are already assumed to have `root` on the host machine, there are deliberately no protections against admins inputting malicious config values, attempts to attack other admin users, or destructive/malicious actions. Permissions for non-logged in users are managed via the [`PERMISSIONS`](https://github.com/archiveBox/archiveBox/wiki/configuration#permissions) + [`PUBLIC_INDEX` + `PUBLIC_ADD_VIEW`](https://github.com/archiveBox/archiveBox/wiki/configuration#public_index--public_add_view) + other config options.

### Sanitization of Config Values, Filesystem Paths, DB Fields, etc.

Non-logged in users can only choose between public Persona config presets on the `/add/` page, but they should never be allowed to directly set config options like `*_ARGS`, `*_BINARY` or DB fields like `url`, `title`, `tag.name`, `notes` without sanitization/filtering on save and/or use.

Non-logged in users should be tightly limited to prevent attacks like SQL/shell injection, path traversal attacks, XSS, cookie leaks between admin/non-admin domains, etc. Any reports related to non-logged-in users will be prioritized as this is a surface we care a lot about hardening.

### XSS, CSRF, CORS, CSP

`< v0.9.x` versions do not include any XSS/CSRF protections at all, as documented in the [readme](https://github.com/ArchiveBox/ArchiveBox/tree/v0.7.4#security-risks-of-viewing-archived-js), [wiki](https://github.com/ArchiveBox/ArchiveBox/wiki/Publishing-Your-Archive#security-concerns), [issue #239](https://github.com/ArchiveBox/ArchiveBox/issues/239), and [existing advisory](https://github.com/ArchiveBox/ArchiveBox/security/advisories/GHSA-cr45-98w9-gwqx). Do not open advisories related to XSS or CSRF for those versions, as they are missing fundamental architectural changes added in `v0.9.0` needed to support per-snapshot replay isolation.

[`SERVER_SECURITY_MODE`](https://github.com/archiveBox/archiveBox/wiki/configuration#server_security_mode) + CSRF/XSS defenses were only added in the new 0.9.0 `dev` work and are planned to land in `main` in mid-2026.

Note archivebox is designed to be able to archive any URL the server can reach, including internal intranet URLs. The only URLs that are blocked are URLs hosted by the archivebox server itself.
