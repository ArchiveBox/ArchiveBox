#!/usr/bin/env sh
# DNS-01 wildcard cert sidecar for the bundled ArchiveBox reverse-proxy profile.
#
# ArchiveBox serves unlimited dynamically-generated snapshot subdomains
# (snap-<id>.<base>), so per-host cert issuance can't scale — we obtain ONE
# `*.<base>` wildcard cert via DNS-01 and let Caddy serve it for every subdomain.
#
# Provider coverage is delegated entirely to go-acme/lego, which speaks DNS-01
# to ~150 providers (cloudflare, route53/AWS, gcloud, digitalocean, hetzner,
# namecheap, godaddy, ...). We do NOT hand-code providers here: you pick one
# with ARCHIVEBOX_PROXY_DNS_PROVIDER and pass its credentials through as the
# standard env vars lego documents for that provider, e.g.
#   cloudflare  -> CLOUDFLARE_DNS_API_TOKEN
#   route53     -> AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION
#   gcloud      -> GCE_PROJECT / GOOGLE_APPLICATION_CREDENTIALS
#   digitalocean-> DO_AUTH_TOKEN
#   hetzner     -> HETZNER_API_KEY
#   namecheap   -> NAMECHEAP_API_USER / NAMECHEAP_API_KEY
#   godaddy     -> GODADDY_API_KEY / GODADDY_API_SECRET
# Full list + var names: https://go-acme.github.io/lego/dns/
set -eu

DOMAIN="${ARCHIVEBOX_PROXY_DOMAIN:?set ARCHIVEBOX_PROXY_DOMAIN to your base domain, e.g. archive.example.com}"
PROVIDER="${ARCHIVEBOX_PROXY_DNS_PROVIDER:?set ARCHIVEBOX_PROXY_DNS_PROVIDER to a lego DNS provider, e.g. cloudflare}"
EMAIL="${ARCHIVEBOX_PROXY_ACME_EMAIL:?set ARCHIVEBOX_PROXY_ACME_EMAIL to a contact email for ACME}"
CERT_DIR="${ARCHIVEBOX_PROXY_CERT_DIR:-/certs}"
LEGO_PATH="${CERT_DIR}/lego"
RENEW_INTERVAL="${ARCHIVEBOX_PROXY_RENEW_INTERVAL:-43200}" # 12h
# Staging CA for testing avoids burning prod rate limits; set =1 to use it.
CA_FLAG=""
if [ "${ARCHIVEBOX_PROXY_ACME_STAGING:-0}" = "1" ]; then
	CA_FLAG="--server=https://acme-staging-v02.api.letsencrypt.org/directory"
fi

mkdir -p "${LEGO_PATH}"

# lego writes wildcard certs as `_.<domain>.crt` / `.key`; publish them under
# the stable names the Caddyfile points at (ARCHIVEBOX_PROXY_TLS).
publish() {
	src="${LEGO_PATH}/certificates/_.${DOMAIN}"
	if [ -f "${src}.crt" ] && [ -f "${src}.key" ]; then
		cp -f "${src}.crt" "${CERT_DIR}/wildcard.crt"
		cp -f "${src}.key" "${CERT_DIR}/wildcard.key"
		echo "[proxy_lego] published *.${DOMAIN} wildcard cert -> ${CERT_DIR}/wildcard.{crt,key}"
	else
		echo "[proxy_lego] expected cert at ${src}.{crt,key} not found" >&2
		return 1
	fi
}

# One `run` to issue, then `renew` on each later pass (lego no-ops if not due).
ACTION="run"
while true; do
	echo "[proxy_lego] ${ACTION} *.${DOMAIN} via ${PROVIDER} (DNS-01)"
	if lego --accept-tos --email "${EMAIL}" --dns "${PROVIDER}" \
		--domains "*.${DOMAIN}" --domains "${DOMAIN}" \
		--path "${LEGO_PATH}" ${CA_FLAG} "${ACTION}" ${RENEW_FLAGS:-}; then
		publish || true
	else
		echo "[proxy_lego] lego ${ACTION} failed; will retry next interval" >&2
	fi
	ACTION="renew"
	RENEW_FLAGS="--days 30"
	sleep "${RENEW_INTERVAL}"
done
