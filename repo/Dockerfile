FROM python:3.11-slim

WORKDIR /app

RUN useradd -m -u 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data && chown appuser:appuser /data

USER appuser

ENV PYTHONPATH=/app
ENV FLASK_APP=wsgi:app

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "60", "wsgi:app"]
