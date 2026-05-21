# Deployment & hardening (cloud phase)

Not needed for local dev. This is the plan for the isolated VPS later.

## Topology

The internet-facing box serves **static files only**. The pipeline (which holds
the mailbox password and AI key) should run either:

- as an **isolated non-web user** on the same small VPS (simplest), with the web
  user having no access to `.env`; or
- on a **separate machine** and rsync the approved static output to the web box
  (most isolated).

Either way, no secret and no runtime sits on the public surface.

## Host hardening checklist

- SSH: key-only (`PasswordAuthentication no`), root login disabled, ideally a
  non-standard port and/or restricted by firewall.
- Firewall (UFW): allow only 80, 443, and SSH; deny everything else inbound.
- `fail2ban` on SSH.
- `unattended-upgrades` for automatic security patches.
- Nginx serves the static root; no PHP, no app server, no autoindex.
- TLS via Let's Encrypt (certbot), HSTS, `server_tokens off`.
- Security headers: `Content-Security-Policy` (the site needs only self + Google
  Fonts), `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options`.
- `.env` mode `600`, owned by the pipeline user only.

## Weekly schedule

Cron the draft build for Monday morning; publishing stays manual (review gate):

```cron
# Monday 06:00 — build the draft and notify for review
0 6 * * 1  cd /opt/wum/pipeline && /usr/bin/python3 run.py >> /var/log/wum.log 2>&1
```

After reviewing the draft, promote it:

```bash
python3 run.py --publish
```

(Once we trust the output, the publish step can be folded into the cron job.)

## Nginx (sketch)

```nginx
server {
    listen 443 ssl http2;
    server_name whatsupmissoula.com;
    root /var/www/wum;            # = pipeline output_dir
    index index.html;
    server_tokens off;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header Referrer-Policy strict-origin-when-cross-origin;
    location / { try_files $uri $uri/ =404; }
}
```
