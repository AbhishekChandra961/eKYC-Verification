#!/bin/sh
# Runs at container start (the nginx image runs every script in /docker-entrypoint.d/ before nginx starts).
# Writes the API address the BROWSER must call into /config.js, which index.html loads before the app.
set -eu
case "${EKYC_API_URL:-}" in
  http://*|https://*) ;;
  *) echo "EKYC_API_URL must start with http:// or https:// (got '${EKYC_API_URL:-}')" >&2; exit 1 ;;
esac
case "$EKYC_API_URL" in
  *\"*|*\\*|*\'*|*\<*) echo "EKYC_API_URL contains a quote, backslash or <" >&2; exit 1 ;;
esac
printf 'window.EKYC_CONFIG = { apiUrl: "%s" }\n' "$EKYC_API_URL" > /usr/share/nginx/html/config.js
echo "ekyc: API address for the browser: $EKYC_API_URL"
