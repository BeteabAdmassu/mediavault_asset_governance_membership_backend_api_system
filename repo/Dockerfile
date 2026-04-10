FROM python:3.11-slim

WORKDIR /app

RUN useradd -m -u 1000 appuser

# Install curl for the Docker healthcheck (not present in python:3.11-slim by default)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data && chown appuser:appuser /data

USER appuser

ENV PYTHONPATH=/app
ENV FLASK_APP=wsgi:app

EXPOSE 5000

# Single worker is required when using the in-memory rate-limit backend.
# Multiple workers would give each process a separate counter, making per-IP/user
# rate limits non-deterministic.  This deployment is already single-machine
# (SQLite), so a single worker is the correct production setting.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "60", "wsgi:app"]
