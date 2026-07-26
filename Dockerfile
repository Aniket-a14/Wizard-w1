# Backend API image.
#
# Python 3.11 to match `target-version` in pyproject.toml and the version CI
# tests against; the previous 3.10 base meant the deployed runtime was never the
# runtime the test suite exercised.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    ENV=prod

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

# Present for deployments that do NOT mount the Docker socket. docker-compose
# overrides this to root, because talking to the host daemon needs socket
# access — see the comment there.
RUN adduser --disabled-password --gecos '' appuser && \
    mkdir -p /app/data /app/logs && \
    chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "src.api.api:app", "--host", "0.0.0.0", "--port", "8000"]
