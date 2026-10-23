# Saved HTML with mixed newlines

Byte-exact public Open Graph metadata excerpt from the captured Divoom product page
https://divoom.com/products/pixoo-64, inspected on 2026-10-23. It contains standalone
CR characters as well as CRLF and LF. HTMLParser counts only LF for source positions;
str.splitlines also counts standalone CR, shifting later resource replacements.

The gzip preserves the original newline bytes across checkouts. Tests insert this
real metadata into the head of the existing recorded crontab.guru page and serve its real captured
resources, exercising the shared replay path without relying on this site's scripts.

Excerpt SHA256: `76d97e17b91e079d550d41fea10bab3c14a891ac5d86ba56f87e3a8f460b39d6`
