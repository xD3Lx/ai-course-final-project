#!/bin/sh
# Start the FastAPI backend (internal) and the Streamlit UI (public) together.
# Streamlit listens on $PORT (Fly maps the public 8080 to it); the backend stays
# on localhost and is reached by the UI via API_BASE_URL.
set -e

BACKEND_PORT="${BACKEND_PORT:-8000}"
UI_PORT="${PORT:-8080}"
export API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:${BACKEND_PORT}}"

# Backend in the background. Settings are read from environment variables
# (set via `fly secrets set`); no --env-file needed in the container.
uvicorn app.api.main:app --host 127.0.0.1 --port "${BACKEND_PORT}" &
BACKEND_PID=$!

# If the backend dies, take the whole container down so Fly restarts it.
trap 'kill "${BACKEND_PID}" 2>/dev/null || true' EXIT

# UI in the foreground (PID 1 signal handling).
exec streamlit run app/ui/streamlit_app.py \
    --server.port "${UI_PORT}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
