# Используем официальный Python образ
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Копируем файлы зависимостей
COPY backend/requirements.txt ./requirements.txt

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY backend/. .
COPY templates ./templates

# Создаем пользователя для безопасности
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Создаем необходимые директории
RUN mkdir -p /app/data/tasks /app/data/logs

# Открываем порт
EXPOSE 8080

# Дефолтный порт для приложения
ENV PORT=8080

# Команда для запуска приложения
CMD ["python", "run.py"]
