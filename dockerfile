FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
ENV PYTHONPATH=/app/ugc:/app

WORKDIR /app/ugc
RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

USER app

EXPOSE 8000

CMD ["uvicorn", "ugc.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]