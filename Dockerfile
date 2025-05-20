FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Фиктивный порт для совместимости с платформой
EXPOSE 8080

CMD ["python", "main.py"]