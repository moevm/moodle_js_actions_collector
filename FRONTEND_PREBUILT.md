# Запуск интерфейса без npm

Этот пакет содержит ранее успешно собранный интерфейс из версии проекта Moodle 5.0.2.
Архив распаковывается в корень существующего проекта, рядом с docker-compose.yaml.
Меняется только способ упаковки frontend: готовый dist копируется в nginx:1.28-alpine.
Данные Moodle, MongoDB, .env и backend не затрагиваются.

1. Сохраните frontend-prebuilt.zip в корень проекта.
2. Выполните:

```bash
unzip -o frontend-prebuilt.zip
docker compose --progress plain build --pull=false frontend
docker compose up -d --no-build --pull never --wait --wait-timeout 900
```

Node, npm и обращение к npm registry при этой сборке не используются.
Образ nginx:1.28-alpine уже загружен вами через Skopeo.
Полный запуск проекта здесь не проверен — Docker daemon в среде подготовки отсутствует.
Сам production dist собран успешно и проверен на наличие локальных assets.

Адрес статистики: http://localhost:18081
Логин: collector@example.com
Пароль: CollectorLocal123!

Это снимок интерфейса, а не автоматическая пересборка исходников.
После изменения Vue-исходников требуется заново собрать dist либо использовать
сохранённый client/Dockerfile.source в среде с рабочим доступом к npm registry.
Исходная .dockerignore для source-сборки не должна исключать package.json и src.
