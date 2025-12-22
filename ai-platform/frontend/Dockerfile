# Этап сборки
FROM node:18-alpine as build

WORKDIR /app

# Копируем package.json
COPY package*.json ./

# Устанавливаем зависимости
RUN npm ci --only=production

# Копируем исходный код
COPY . .

# Сборка приложения
RUN npm run build

# Этап production
FROM nginx:alpine

# Копируем собранное приложение
COPY --from=build /app /usr/share/nginx/html

# Копируем конфигурацию nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Открываем порт
EXPOSE 80

# Команда запуска
CMD ["nginx", "-g", "daemon off;"]
