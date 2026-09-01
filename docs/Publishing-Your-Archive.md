# Publishing Your Archive

There are two ways to publish your archive: using the `archivebox server` or by exporting and hosting it as static HTML.

<br/>

## 1. Use the built-in web server

```bash
# start the webserver
archivebox server 0.0.0.0:8000
```

Open <http://admin.archivebox.localhost:8000/admin/> in a browser to create the first admin and finish web setup. To create additional accounts from the CLI, use `archivebox manage createsuperuser`.

This server is enabled out-of-the-box if you're using `docker-compose` to run ArchiveBox.
If `BASE_URL` is not configured yet, complete the first-run wizard before exposing ArchiveBox. It guides you through choosing a security mode and shows the settings to enter in Cloudflare, Nginx Proxy Manager, Caddy, Traefik, Tailscale, or your hosting platform's ingress UI. Configure HTTPS there, then open the canonical URL you chose in the wizard. Existing `BASE_URL` and security settings are trusted, so configured servers skip this wizard.

After ingress is working, set the permissions depending on how public you want the archive to be:

```bash
archivebox config --set PUBLIC_INDEX=True
archivebox config --set PUBLIC_ADD_VIEW=True
archivebox config --set PERMISSIONS=public
```

> [!TIP]
> Advanced: You can use nginx to serve a static export directly from the filesystem. Do not proxy live replay paths back onto the admin origin; use ArchiveBox's security-mode routing.

<br/>

## 2. Export and host it as static HTML

```bash
archivebox list --html --with-headers > index.html
archivebox list --json --with-headers > index.json

# then upload the entire output folder containing index.html and archive/ somewhere
# e.g. github pages or another static hosting provider

# you can also serve it with the simple python HTTP server
python3 -m http.server --bind 0.0.0.0 --directory . 8000
open http://127.0.0.1:8000
```

Here's a sample nginx configuration that works to serve your static archive folder:

```nginx
location / {
    alias       /path/to/your/ArchiveBox/data/;
    index       index.html;
    autoindex   on;
    try_files   $uri $uri/ =404;
}
```

Make sure you're not running any content as CGI or PHP, you only want to serve static files!

The generated links are relative, so the export works at a domain root or a project subpath such as GitHub Pages. Snapshot pages and outputs remain under their real filesystem paths, for example:

`archive/users/alice/snapshots/20260829/example.com/SNAPSHOT_UUID/index.html`

ArchiveBox does not create top-level timestamp symlinks for current snapshots. Run `archivebox update --migrate-only` to move real legacy `archive/<timestamp>/` directories into the user-scoped layout and remove obsolete timestamp projections.

<br/>

---

<br/>

## Security Concerns

> [!CAUTION]
> Re-hosting untrusted archived content on the same origin as an authenticated application can compromise that application.

Make sure you understand the dangers of [hosting untrusted HTML/JS/CSS](https://developer.mozilla.org/en-US/docs/Web/Security/Same-origin_policy). The default `SERVER_SECURITY_MODE=auto` uses isolated subdomains with full replay on `*.localhost`, and a one-domain no-JS replay policy on ordinary public or LAN hostnames. Choose `safe-subdomains-fullreplay` only when wildcard DNS and TLS for `*.archive.example.com` are configured; it separates the admin, web, and API control planes from replay content and gives each Snapshot its own replay subdomain.

Do not serve the authenticated ArchiveBox application from a shared subdirectory such as `myapps.example.com/archivebox/`; it cannot provide the required origin isolation. A standalone static export can be hosted at a project subpath because it contains no authenticated control plane. If you do not need JavaScript-capable replay, you can also disable the relevant extractors with `WGET_ENABLED=False` and `DOM_ENABLED=False`.

More info:
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#publishing
- https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview#%EF%B8%8F-things-to-watch-out-for-%EF%B8%8F

<br/>

---

<br/>

## Copyright Concerns

> [!WARNING]
> Be aware that some sites you archive may not allow you to rehost their content publicly for copyright reasons, it's up to you to host responsibly and respond to takedown requests appropriately based on the laws in your jurisdiction.

Archiving for personal backups, research, and some other use-cases are covered by [fair use copyright exemptions](https://guides.library.oregonstate.edu/copyright/libraries) in the USA, but if your archive can deprive the original author of revenue (e.g. if you rehost it for profit), then your use case might no longer be covered and you have to respond to DMCA takedown notices.

**As a general rule of thumb:**

- Copies cannot be made for commercial purposes
- The copying cannot be systematic (e.g., to replace subscriptions)
- All copies made must include a notice stating that the materials may be protected under copyright.

Please modify the [`FOOTER_INFO`](https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#footer_info) config variable to add your contact info to the footer of your index.

Note: ArchiveBox prevents search engines from indexing your archives using [`/robots.txt`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/templates/static/robots.txt#L2) by default. It is not recommended to override this file in the collection's fixed `custom_templates/` directory, as public indexing often leads to automated takedown requests and abuse reports.

*Keep in mind individuals, companies, schools, and libraries all have different copyright exemptions in different countries. Double check the specific laws for your situation in your own jurisdiction!*

#### Further Reading: USA Copyright Law & Fair Use Exemptions

- https://www.copyright.gov/title17/
- https://help.archive.org/help/rights/
- https://blog.archive.org/2024/03/01/fair-use-in-action-at-the-internet-archive/
- https://www.lib.ncsu.edu/workshops/understanding-copyright-and-fair-use-archival-research
- https://libguides.colorado.edu/c.php?g=1154758&p=8428124
- https://fairuse.stanford.edu/2003/11/10/digital_preservation_and_copyr/
- https://guides.library.oregonstate.edu/copyright/libraries
- https://www.clir.org/pubs/reports/pub112/body/
- https://github.com/pirate/internet-archiving-talk
