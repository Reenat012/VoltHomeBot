# Используем актуальный образ Python
FROM python:3.10-slim

# Установка зависимостей
WORKDIR /app

# Установка зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Копирование зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Экспорт порта (если используется веб-сервер)
EXPOSE 8000

# Запуск бота
CMD ["python", "main.py"]