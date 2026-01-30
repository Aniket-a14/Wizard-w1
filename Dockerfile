# Base Image: Lightweight Python
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Environment Variables
ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  ENV=prod

# Install system dependencies (for matplotlib/scipy if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ . 

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser
USER appuser

# Health Check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Command
CMD ["uvicorn", "src.api.api:app", "--host", "0.0.0.0", "--port", "8000"]
