# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 — builder: pip-install dependencies into an isolated venv.
# The venv is copied wholesale to the runtime stage; pip and the build cache
# stay here and never reach the final image.
# ---------------------------------------------------------------------------
FROM python:3.14-slim-trixie AS builder

WORKDIR /app

# Self-contained virtualenv we can copy to stage 2. It references
# /usr/local/bin/python, which also exists in the (identical) runtime base.
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install dependencies first, in their own layer, for caching. requirements.txt
# carries the --extra-index-url for the CPU-only torch wheels. The pip cache is
# a BuildKit cache mount, so it never lands in an image layer.
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Then add the application source.
COPY . /app

# ---------------------------------------------------------------------------
# Stage 2 — runtime: clean Python image with only the venv + app source.
# No pip cache, no build tooling.
# ---------------------------------------------------------------------------
FROM python:3.14-slim-trixie AS runtime

# Non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

WORKDIR /app

# Copy the ready-made venv and the application code from the builder.
COPY --from=builder --chown=nonroot:nonroot /app /app

# Put the venv on PATH; sensible Python + Streamlit runtime defaults.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BACKEND_PORT=8000 \
    PORT=8080 \
    API_BASE_URL=http://127.0.0.1:8000 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN chmod +x /app/start.sh

USER nonroot

# Streamlit UI (public). The FastAPI backend runs internally on BACKEND_PORT.
EXPOSE 8080

# Launch both processes (backend in background, Streamlit in foreground).
CMD ["sh", "/app/start.sh"]
