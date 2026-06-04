# Example etc files for deploying ArchiveBox

In this folder are some example config files you can use for setting up ArchiveBox on your machine.

E.g. see `nginx.conf` for an example nginx config to serve your archive with SSL, or `fly.toml` for an example deployment to the Fly.io hosting platform.

For the recommended, batteries-included reverse proxy, see `Caddyfile` — it's used by
the opt-in `docker-compose.proxy.yml` overlay to wildcard-route every dynamically
generated snapshot/role subdomain to ArchiveBox and terminate TLS. Locally it serves
`*.archivebox.localhost` via Caddy's internal CA; publicly it serves a single
`*.<your-domain>` wildcard cert obtained via DNS-01 by the `goacme/lego` sidecar
(`../bin/proxy_lego.sh`), which covers unlimited `snap-*` subdomains with one cert and
supports ~150 DNS providers without any per-provider code. See `../.env.proxy.example`.

Please contribute your etc files here! Example contributions

- supervisord config
- systemd config
- apache webserver config
- other init system, webservers, or scheduler configs
