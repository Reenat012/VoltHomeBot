# База с актуальными репозиториями Debian
FROM python:3.10-slim-bullseye

# Не писать .pyc и сразу логировать в stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Если нужны нативные зависимости для сборки (cryptography и т.п.)
# Если не нужны — можно удалить весь этот RUN-блок.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY . .

# Порт вебхука (можно переопределить переменными окружения)
EXPOSE 8000

# Запуск бота (webhook/polling определяется твоим main.py)
CMD ["python", "main.py"]