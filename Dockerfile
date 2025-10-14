# Актуальная база Debian
FROM python:3.10-slim-bullseye

# Не писать .pyc и логировать в stdout; отключить кеш pip
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Нативные зависимости (нужны для сборки некоторых колёс, можно удалить, если не требуется)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

# Сначала зависимости — лучше кэшируется
COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# Затем код
COPY . .

# Порт вебхука
EXPOSE 8000

# Запуск
CMD ["python", "main.py"]