# Backend API image.
#
# Python 3.11 to match `target-version` in pyproject.toml and the version CI
# tests against; the previous 3.10 base meant the deployed runtime was never the
# runtime the test suite exercised.
#
# Two things are deliberately *not* installed here:
#
#   build-essential   ~250 MB of compiler toolchain for a dependency set that is
#                     entirely manylinux wheels on cp311. It was only ever
#                     needed by a package that no longer appears below.
#   curl              the healthcheck runs on the interpreter that is already
#                     here, so the image needs no apt layer at all.
#
# Generated code does not run in this image -- it runs in `backend/docker` or in
# a local subprocess -- so the analysis toolkit is not installed here either.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    ENV=prod

COPY requirements.txt .
RUN pip install --no-cache-dir --compile -r requirements.txt

COPY backend/ .

# Present for deployments that do NOT mount the Docker socket. docker-compose
# overrides this to root, because talking to the host daemon needs socket
# access — see the comment there.
RUN adduser --disabled-password --gecos '' appuser && \
    mkdir -p /app/data /app/logs && \
    chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"]

EXPOSE 8000

CMD ["uvicorn", "src.api.api:app", "--host", "0.0.0.0", "--port", "8000"]
