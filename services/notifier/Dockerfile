FROM python:3.13.7-slim-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY services/notifier/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/notifier/ ./

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
USER app
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "notifier:app"]
