# Thin Conxa cloud SaaS backend.
#
# Build context MUST be the repo root so the shared foundation is reachable:
#   docker build -f conxa-cloud/backend/Dockerfile -t conxa-cloud .
#
# No Playwright/Chromium here — recording and compiling happen in the local
# Build Studio, not in the cloud.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the shared foundation first (changes least often -> better layer cache).
COPY packages/conxa-core /src/packages/conxa-core
RUN pip install --upgrade pip && pip install /src/packages/conxa-core

# Install cloud dependencies.
COPY conxa-cloud/backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Application code.
COPY conxa-cloud/backend/app ./app

EXPOSE 8000

# Schema is created by init_db() at startup; readiness is gated by /readyz.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
