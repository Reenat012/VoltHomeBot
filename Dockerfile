# Используем официальный образ Python
FROM python:3.10-slim-buster

# Создаем рабочую директорию
WORKDIR /app

# Копируем зависимости сначала для кэширования
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальные файлы
COPY . .

# Открываем порт для вебхука
EXPOSE 8000

# Запускаем бота
CMD ["python", "main.py"]