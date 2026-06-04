# Example etc files for deploying ArchiveBox

In this folder are some example config files you can use for setting up ArchiveBox on your machine.

E.g. see `nginx.conf` for an example nginx config to serve your archive with SSL, or `fly.toml` for an example deployment to the Fly.io hosting platform.

For the recommended, batteries-included reverse proxy and TLS, you don't need a file
here at all — it's built into the main `../docker-compose.yml` as two opt-in, env-var
driven profiles (no extra files, Dockerfiles, or scripts) — set the documented env
vars in a `.env` next to `../docker-compose.yml`:

- `https` — Caddy + a `goacme/lego` DNS-01 sidecar fetch a single `*.<your-domain>`
  wildcard cert (covering unlimited `snap-*` subdomains, ~150 DNS providers, no
  per-provider code) and serve it, gracefully degrading to a self-signed cert if none
  is available yet.
- `tunnel` — a Cloudflare Tunnel whose tunnel/DNS are auto-provisioned from your API
  token, so Cloudflare's edge terminates TLS and routes `*.<your-domain>` through one
  tunnel to ArchiveBox (Host-routed) — no public IP or wildcard cert needed locally.

Please contribute your etc files here! Example contributions

- supervisord config
- systemd config
- apache webserver config
- other init system, webservers, or scheduler configs
