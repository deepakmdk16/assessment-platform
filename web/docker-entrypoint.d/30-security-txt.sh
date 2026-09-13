#!/bin/sh
# Renders /.well-known/security.txt (RFC 9116) before nginx starts. The stock
# nginx image runs every executable file in /docker-entrypoint.d in name order;
# 20-envsubst-on-templates.sh is the one that renders default.conf.template.
#
# Why generated rather than a file in web/public/: both required fields are
# deployment state. `Contact` is the operator's address (SECURITY_CONTACT,
# falling back to the platform's own SUPPORT_EMAIL so a small deployment sets
# one address, not two), and `Expires` is a MUST that has to be a real date in
# the future — baked at build time it would go stale on the shelf, and an
# expired security.txt is treated as no security.txt.
#
# With no address configured nothing is published: an empty Contact makes the
# file invalid, so a 404 is the honest answer.
set -eu

root="${SECURITY_TXT_ROOT:-/usr/share/nginx/html}"
out="$root/.well-known/security.txt"
contact="${SECURITY_CONTACT:-${SUPPORT_EMAIL:-}}"

if [ -z "$contact" ]; then
    rm -f "$out"
    echo "$0: no SECURITY_CONTACT or SUPPORT_EMAIL set, not publishing security.txt"
    exit 0
fi

# 12 months out, the maximum the spec recommends. Done with string arithmetic
# because relative dates are spelled three different ways: `date -v+1y` (BSD,
# the developer host these tests run on), `date -d '+1 year'` (GNU) and
# `date -D` (busybox, which is what is actually in the image).
now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
expires="$(( ${now%%-*} + 1 ))${now#????}"
# 29 February has no anniversary; the next instant that exists is 1 March.
case "$expires" in
    *-02-29T*) expires="${expires%%-*}-03-01${expires#*-02-29}" ;;
esac

# An address gets the mailto: scheme; anything already carrying a scheme — a
# disclosure form, a bug-bounty page — is published as the URI it is. No address
# can contain a colon, so the test is unambiguous.
case "$contact" in
    *:*) ;;
    *) contact="mailto:$contact" ;;
esac

mkdir -p "$root/.well-known"
{
    echo "Contact: $contact"
    echo "Expires: $expires"
    # Optional, and only meaningful once the public host is known — it is what
    # lets a reader tell this file apart from a copy served somewhere else.
    if [ -n "${PUBLIC_BASE_URL:-}" ]; then
        echo "Canonical: ${PUBLIC_BASE_URL%/}/.well-known/security.txt"
    fi
} >"$out"

echo "$0: published security.txt (Contact: $contact, Expires: $expires)"
