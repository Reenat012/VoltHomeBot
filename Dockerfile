FROM python:3.10-slim

# Установка Redis и создание директории данных
RUN apt-get update && apt-get install -y \
    redis-server \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data

# Установка зависимостей Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Порт для веб-сервера
EXPOSE 8000

# Команда запуска
CMD ["sh", "-c", "redis-server --daemonize yes && sleep 2 && python main.py"]