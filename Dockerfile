FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /code

# gosu drops privileges in the entrypoint after it has handed the mounted disk
# over to appuser — see entrypoint.sh.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first, so editing code doesn't reinstall the world on every
# deploy. The build backend refuses to even read the requirements unless the
# package directory exists, so it gets an empty one that is thrown away again —
# the real code arrives below and is installed without re-resolving anything.
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install --upgrade pip \
    && pip install . \
    && rm -rf app

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY entrypoint.sh ./
RUN pip install --no-deps .

# Don't run as root. The entrypoint starts as root only long enough to chown
# the disk, then execs the server as this user.
RUN useradd --create-home --uid 1000 appuser \
    && chmod +x entrypoint.sh \
    && chown -R appuser:appuser /code

EXPOSE 8000

ENTRYPOINT ["/code/entrypoint.sh"]

# Bound to $PORT because that is what the host tells us to listen on — Render
# fails the deploy if it can't find a bound port, and its default is 10000, not
# 8000. One worker on purpose: the cast channel's subscriber list lives in
# process memory, so a second worker would leave half the displays unnotified.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
