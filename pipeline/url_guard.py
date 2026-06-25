"""Validate outbound URLs before the pipeline fetches them.

The pipeline screenshots / downloads whatever URL an incoming flyer email links
to. Without a guard, a crafted link could read local secrets or hit internal
services (SSRF):

    file:///app/.env            -> the IMAP password + Anthropic API key
    http://169.254.169.254/     -> cloud metadata
    http://127.0.0.1:.../       -> anything bound to localhost on the VPS

Every outbound fetch — chromium screenshots and urllib downloads alike — must
pass its URL through `safe_url()` first.

Residual risk (documented, not yet closed): the real fetcher re-resolves DNS and
follows HTTP redirects, so a determined attacker could DNS-rebind or 30x-redirect
to an internal address *after* this check. Blocking the schemes plus the
current-resolution / literal-IP cases covers the realistic crafted-link threat;
connecting to the pinned, validated IP (and re-validating each redirect hop)
would be the next hardening step.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """Raised for a URL we refuse to fetch (bad scheme or non-public host)."""


def _is_public(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local      # 169.254/16 — incl. cloud metadata
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified     # 0.0.0.0 / ::
    )


def safe_url(url: str) -> str:
    """Return `url` unchanged if it's safe to fetch, else raise UnsafeURLError.

    Rejects non-http(s) schemes (kills file://, data:, javascript:, ftp://) and
    hosts that resolve to private / loopback / link-local / metadata addresses.
    """
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"scheme not allowed: {parts.scheme!r} in {url!r}")
    host = parts.hostname
    if not host:
        raise UnsafeURLError(f"no host in URL: {url!r}")
    try:
        infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"cannot resolve host {host!r}: {e}") from e
    for info in infos:
        ip = info[4][0]
        if not _is_public(ip):
            raise UnsafeURLError(f"host {host!r} resolves to non-public address {ip}")
    return url


def is_http_url(url: str) -> bool:
    """Cheap scheme-only check (no DNS) — for filtering candidate links."""
    return urlsplit((url or "").strip()).scheme.lower() in ALLOWED_SCHEMES
