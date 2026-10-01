# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.11

# ---------- builder : résout et installe les dépendances avec uv ----------
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# "" pour l'API, "--group ui" pour Streamlit
ARG UV_SYNC_ARGS=""

WORKDIR /app

# 1) dépendances seules : couche mise en cache tant que uv.lock ne change pas
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev ${UV_SYNC_ARGS}

# 2) le code, installé comme un vrai package (pas en editable)
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable ${UV_SYNC_ARGS}

# ---------- runtime : pas de uv, pas de sources, utilisateur non-root ----------
FROM python:${PYTHON_VERSION}-slim AS runtime

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
 && mkdir -p /data/db \
 && chown app:app /data/db

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app config ./config
COPY --chown=app:app skills ./skills
COPY --chown=app:app ui ./ui

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "sql_ai_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]