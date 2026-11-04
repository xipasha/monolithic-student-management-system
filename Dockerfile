
FROM python:3.13.7-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY courses_client.py .
COPY notifications.py .
COPY services/ ./services/
COPY templates/ ./templates/

RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/instance \
    && chown app:app /app/instance

USER app

EXPOSE 8000

CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 \"${APP_MODULE:-app:app}\""]
