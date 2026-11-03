# CareerOS: one container, dashboard + worker + daily schedule.
# Base image is a build argument so it can be swapped for a local mirror when testing.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml README.md ./
COPY src/careeros/__init__.py src/careeros/__init__.py
RUN python -m venv /opt/venv \
 && pip install --upgrade pip \
 && pip install .

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY docker/entrypoint.sh /usr/local/bin/careeros-entrypoint
RUN pip install --no-deps . \
 && useradd --create-home --uid 1000 careeros \
 && mkdir -p /app/data /app/exports /app/backups /app/config \
 && chown -R careeros:careeros /app/data /app/exports /app/backups \
 && chmod 0755 /usr/local/bin/careeros-entrypoint \
 && chmod -R a+rX /app/src /app/migrations /app/alembic.ini

USER careeros

# Inside the container the app listens on all interfaces; docker-compose publishes the
# port to 127.0.0.1 only. CAREEROS container mode allows exactly that and nothing else.
ENV CONTAINER=true \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    DATABASE_URL=sqlite:////app/data/careeros.db \
    DATA_DIR=/app/data \
    EXPORT_DIR=/app/exports \
    BACKUP_DIR=/app/backups \
    CAREEROS_MIGRATIONS_DIR=/app/migrations

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["careeros-entrypoint"]
CMD ["serve"]
