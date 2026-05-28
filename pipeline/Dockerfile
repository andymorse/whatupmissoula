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
# image. /app/site/output and /app/pipeline/drafts are bind-mounted volumes,
# so wum owns its writable surface and nothing else.
#
# UID/GID are build args so the container user can match the host user that
# owns .env on the VPS (set WUM_UID/WUM_GID in .env to `id -u`/`id -g` of
# the host wum if it isn't 1000:1000).
ARG WUM_UID=1000
ARG WUM_GID=1000
RUN groupadd -g ${WUM_GID} wum \
 && useradd  -u ${WUM_UID} -g ${WUM_GID} -m -d /home/wum wum \
 && mkdir -p /app/site/output /app/pipeline/drafts \
 && chown -R wum:wum /app
USER wum

WORKDIR /app/pipeline
CMD ["python", "run.py"]
