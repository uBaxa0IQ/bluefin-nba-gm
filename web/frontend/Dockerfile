# Stage 1: Build
FROM node:22-alpine AS builder

WORKDIR /app/web/frontend

# Аргумент для API URL (по умолчанию относительный путь для продакшена)
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

# Копируем package files
COPY web/frontend/package*.json ./

# Устанавливаем зависимости
RUN npm ci

# Копируем исходный код
COPY web/frontend/ .
COPY web/bluefin-preview/ ../bluefin-preview/

# Собираем приложение
RUN npm run build

# Stage 2: Production
FROM nginx:alpine

# Копируем собранное приложение
COPY --from=builder /app/web/frontend/dist /usr/share/nginx/html

# Копируем конфигурацию nginx
COPY web/frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

