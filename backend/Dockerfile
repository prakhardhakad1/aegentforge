# AgentForge backend image.
# Build context is the REPO ROOT (docker-compose sets this) so the editable
# orchestrator/tools packages can be copied in.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: none needed beyond stdlib (fpdf2 and matplotlib ship wheels).
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY packages/orchestrator /app/packages/orchestrator
COPY packages/tools /app/packages/tools
RUN pip install --no-cache-dir -e /app/packages/orchestrator -e /app/packages/tools

COPY backend /app/backend

WORKDIR /app/backend
EXPOSE 8000

# RUN_MODE=demo by default so the container works with zero configuration.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
