# Pipeline image: Python + Chromium (web_flyer) + Poppler (pdf2image).
# Designed to run one-shot — `docker compose run --rm pipeline python run.py`.
# Not a long-running service. Caddy is the long-running service; this is the
# weekly job that produces the static HTML Caddy serves.
FROM python:3.12-slim-bookworm

# Chromium → headless flyer rendering (pipeline/web_flyer.py).
# Poppler → PDF page extraction (pdf2image, used in pipeline/extract.py).
# Liberation fonts → keep rendered ad text from falling back to tofu boxes.
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    poppler-utils \
    fonts-liberation \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first so the dep layer caches across code edits.
COPY pipeline/requirements.txt /app/pipeline/requirements.txt
RUN pip install -r /app/pipeline/requirements.txt

# App code. Secrets and state come in at runtime via mounts; never bake them.
COPY pipeline/ /app/pipeline/
COPY site/    /app/site/
COPY ai/      /app/ai/

# Non-root: a bug or SSRF in the pipeline shouldn't be able to touch the
# image. /app/site/output, /app/pipeline/drafts and /app/pipeline/state are
# mounted volumes, so wum owns its writable surface and nothing else.
#
# UID/GID are build args so the container user can match the host user that
# owns .env on the VPS (set WUM_UID/WUM_GID in .env to `id -u`/`id -g` of
# the host wum if it isn't 1000:1000).
ARG WUM_UID=1000
ARG WUM_GID=1000
# Reuse the group/user if the GID/UID is already present in the base image
# (e.g. a host user that shares a GID with an existing image group), so a
# collision doesn't fail the build. UID/GID 0 is rejected outright: running
# the pipeline as root would defeat the non-root hardening above — set
# WUM_UID/WUM_GID to a real unprivileged host user instead.
RUN set -eux; \
    if [ "${WUM_UID}" = "0" ] || [ "${WUM_GID}" = "0" ]; then \
        echo "WUM_UID/WUM_GID must not be 0 (root); use an unprivileged host user" >&2; \
        exit 1; \
    fi; \
    if ! getent group "${WUM_GID}" >/dev/null; then groupadd -g "${WUM_GID}" wum; fi; \
    if ! getent passwd "${WUM_UID}" >/dev/null; then \
        useradd -u "${WUM_UID}" -g "${WUM_GID}" -m -d /home/wum wum; \
    fi; \
    mkdir -p /app/site/output /app/pipeline/drafts /app/pipeline/state; \
    chown -R "${WUM_UID}:${WUM_GID}" /app
USER ${WUM_UID}:${WUM_GID}

WORKDIR /app/pipeline
CMD ["python", "run.py"]
