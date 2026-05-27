# Slim runtime image for the FastAPI app. Multi-arch base (works on the
# Oracle Ampere ARM64 free tier and on x86). psycopg[binary] bundles libpq
# and uvicorn[standard] ships prebuilt wheels, so no system build deps needed.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first so the layer caches across code-only changes.
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt

# App source (see .dockerignore for what's excluded).
COPY . .

EXPOSE 8000

# Container-level health check mirrors the app's public /healthz endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
