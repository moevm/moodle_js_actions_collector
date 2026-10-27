# Moodle JS Actions Collector

Сборщик действий пользователей Moodle: открытия страниц, клики, прокрутка,
переключение вкладок, copy/paste, факты ввода с клавиатуры, изменения чекбоксов
и выпадающих списков. Данные доступны в таблице, на графике и в JSON-выгрузках.

Плагин Moodle подключает JavaScript, который отправляет события из браузера
в отдельный коллектор: FastAPI + MongoDB + интерфейс Vue. Moodle не ждёт отправки
логов при сохранении ответов. Общая база с Moodle не нужна.

Сохраняются пользователь, курс, полный URL, время, браузер и метаданные страницы.
HTML-снимки, значения полей, нажатые символы и содержимое буфера обмена не отправляются.

## Требования

- Docker Engine и Docker Compose 2.20+; на Windows команды выполняются в WSL.
- Python 3.10+ для подготовки ключей и упаковки плагина.
- Для внешнего Moodle: проверена версия 5.0.2, минимальная версия плагина — 5.0.
  Совместимость с другими версиями требует проверки; Moodle 4.x не поддерживается.

Все команды выполняются из корня репозитория. Node.js, PHP и базы на хосте не нужны.

## Локальный стенд

```bash
[ -f .env ] || cp .env.example .env
python3 scripts/init-auth-secrets.py &&
docker compose pull mongodb mariadb &&
docker compose build --pull=false backend frontend moodle &&
docker compose up -d --no-build --wait --wait-timeout 900
```

При первом запуске устанавливается чистый Moodle с демокурсом и включённым плагином.

| Сервис / пользователь | Адрес | Логин | Пароль из примера |
| --- | --- | --- | --- |
| Moodle / администратор | http://localhost:18082 | `admin` | `AdminLocal123!` |
| Moodle / студент | http://localhost:18082 | `student` | `StudentLocal123!` |
| Moodle / преподаватель | http://localhost:18082 | `teacher` | `TeacherLocal123!` |
| Коллектор | http://localhost:18081 | `collector@example.com` | `CollectorLocal123!` |
| Документация API | http://localhost:18080/docs | — | — |

Есть второй студент `student2` с паролем студента. Войдите в Moodle как `student`,
откройте **Collector Demo Course** и выполните несколько действий. Затем войдите
в коллектор и нажмите **Обновить** — должны появиться события с URL этого Moodle.

Для ручной установки плагина в отдельный чистый Moodle: [инструкция](docs/manual-rehearsal.md).

## Подключение существующего Moodle

### 1. Настройте коллектор

Используйте отдельный каталог установки. Этот режим запускает только коллектор,
без тестового Moodle и MariaDB.

```bash
[ -f .env ] || cp .env.example .env
python3 scripts/init-auth-secrets.py
```

Отредактируйте `.env` перед первым запуском:

| Параметр | Значение |
| --- | --- |
| `MOODLE_URL` | Origin Moodle для CORS: например, `https://moodle.example.org`, без пути и завершающего `/` |
| `COLLECTOR_API_URL` | Доступный браузерам адрес API: например, `https://collector.example.org/api` |
| `COLLECTOR_ADMIN_EMAIL`, `COLLECTOR_ADMIN_PASSWORD` | Учётная запись интерфейса коллектора, создаваемая при первой инициализации БД |
| `MONGO_ROOT_USER`, `MONGO_ROOT_PASSWORD` | Отдельные учётные данные MongoDB; замените демонстрационные значения |
| `MONGODB_DATABASE` | Имя базы коллектора |
| `COLLECTOR_PORT`, `COLLECTOR_API_PORT` | Локальные порты интерфейса и API: по умолчанию `18081` и `18080` |
| `COLLECTOR_DB_MAX_SIZE` | Порог хранения, по умолчанию `100GB`; примеры: `500MB`, `10GB`, `100GiB` |
| `COLLECTOR_INGEST_KEY` | Ключ приёма событий; скопируйте его в настройки плагина |
| `COLLECTOR_AUTH_SECRET` | Серверный секрет подписи токенов; оставьте только на коллекторе |
| `COLLECTOR_ACCESS_TOKEN_TTL_SECONDS` | Срок токена интерфейса, по умолчанию `43200` секунд — 12 часов |

Скрипт создаёт только недостающие ключи и сохраняет существующие. Настоящий `.env`
с паролями и ключами не добавляйте в Git. Пароли существующих аккаунтов изменением
`.env` не меняются. Сохраняйте `COMPOSE_PROJECT_NAME` работающей установки, чтобы
подключаться к её прежним томам.

### 2. Соберите и запустите

```bash
docker compose -f docker-compose.prod.yaml pull mongodb &&
docker compose -f docker-compose.prod.yaml build --pull=false backend frontend &&
docker compose -f docker-compose.prod.yaml up -d --no-build --wait --wait-timeout 900
```

Порты привязаны к `127.0.0.1` сервера. Настройте DNS и HTTPS reverse proxy:
весь `https://collector.example.org/`, включая `/api/`, направьте на
`http://127.0.0.1:18081` на сервере. Проверьте доступ с компьютера пользователя.
Для HTTPS Moodle адрес коллектора тоже должен использовать HTTPS.

### 3. Получите архив плагина

На любой машине с исходниками проекта и Python 3.10+:

```bash
python3 scripts/build-moodle-plugin.py
```

Результат: **`dist/local_actioncollector.zip`**. В архив добавляется актуальный
`stat_tracker/collector.js`; тестовая страница исключается. Упаковка не требует
Docker, npm или сети. Архив можно передать администратору Moodle.

### 4. Установите и включите плагин

1. Войдите администратором Moodle.
2. Откройте **Администрирование → Плагины → Установка плагинов**.
3. Загрузите ZIP, проверьте пакет и завершите установку через интерфейс Moodle.
4. Откройте **Администрирование → Плагины → Локальные плагины → Action collector**.
5. Включите **Enable collection**.
6. Укажите **Collector API URL**, например `https://collector.example.org/api`.
7. В **Collection key (write only)** вставьте значение `COLLECTOR_INGEST_KEY`
   из `.env`: только текст после `=`, без имени параметра.
8. Сохраните настройки и перезагрузите открытые страницы Moodle.

Прямые пути: установка — `/admin/tool/installaddon/index.php`,
настройки — `/admin/settings.php?section=local_actioncollector`.

Если установка ZIP запрещена, разместите каталог `actioncollector` из архива
в `<каталог кода Moodle>/local/actioncollector` и завершите обновление через
**Администрирование → Уведомления**. В Docker код плагина должен сохраняться
в образе или постоянном каталоге Moodle.

API вызывается из браузера студента: внутренние имена Docker и `localhost`
чужого компьютера для этого адреса не подходят. Плагин действует на весь сайт
для вошедших пользователей, включая преподавателей и администраторов; гостей
не собирает. Ядро и тему Moodle изменять не требуется.

### 5. Проверьте работу

Войдите обычным пользователем Moodle, откройте курс, нажмите кнопки и введите текст.
В коллекторе нажмите **Обновить**, найдите события по ID пользователя или курсу
и проверьте URL. Метаданные страниц в JSON содержат `page`, `title`, `browser`,
`window`, без HTML. На странице Moodle объект `window.actionCollector` показывает
`ready`, `queued`, `sent`, `dropped` и `error`.

## Если Docker не скачивает образ: skopeo

При зависании на `load metadata` прервите сборку и скачайте проблемный образ
в обход Docker daemon:

```bash
sudo apt-get update && sudo apt-get install -y skopeo
```

В `image` укажите образ из сообщения ошибки:

```bash
image='docker.io/library/python:3.12-slim-bookworm'
image_dir="$(mktemp -d /tmp/collector-image.XXXXXX)" &&
skopeo copy --retry-times 5 \
  "docker://$image" \
  "docker-archive:${image_dir}/image.tar:${image}" &&
docker load --input "$image_dir/image.tar" &&
rm -- "$image_dir/image.tar" &&
rmdir -- "$image_dir"
```

Базовые образы: `python:3.12-slim-bookworm`, `node:22-bookworm-slim`,
`nginx:1.28-alpine`, `alpine:3.22`, `php:8.3-apache-bookworm`, `mongo:8.0.13`,
`mariadb:10.11.11`; для тестов — `mcr.microsoft.com/playwright:v1.63.0-noble`.
Образы без registry в имени находятся в `docker.io/library/`.

После импорта повторите сборку с `--pull=false`; повторный `docker compose pull`
не нужен. npm, pip, apt и Git по-прежнему требуют сеть. Если метаданные снова
не загружаются, проверьте `docker buildx ls`: отдельный builder может использовать
своё хранилище образов.

## Обновление, проверка и остановка

Обновить коллектор, подключённый к существующему Moodle:

```bash
python3 scripts/init-auth-secrets.py &&
docker compose -f docker-compose.prod.yaml build --pull=false backend frontend &&
docker compose -f docker-compose.prod.yaml up -d --no-build --wait --wait-timeout 900 &&
docker compose -f docker-compose.prod.yaml exec -T frontend nginx -s reload
```

При изменении плагина соберите ZIP и установите его обновление в Moodle.
Backend обновляйте раньше плагина, затем перезагрузите открытые страницы.

Для локального стенда:

```bash
python3 scripts/init-auth-secrets.py &&
docker compose build --pull=false backend frontend moodle &&
docker compose up -d --no-build --wait --wait-timeout 900 backend frontend &&
docker compose exec -T frontend nginx -s reload &&
docker compose up -d --no-build --wait --wait-timeout 900 moodle
```

Проверки выполняются на локальном стенде; E2E создают события и ответы в демокурсе:

```bash
docker compose exec -T backend python -m pytest tests -q
docker compose exec -T -e COLLECTOR_RUN_MONGO_TESTS=1 backend \
  python -m pytest tests/test_storage_mongo.py tests/test_security_mongo.py tests/test_exports_mongo.py -q
bash scripts/test.sh
```

Проверки MongoDB используют отдельные временные базы. Отчёт E2E:
`reports/e2e/html/index.html`. Подробнее: [e2e/README.md](e2e/README.md).

Запустить уже собранный локальный стенд: `bash scripts/start-local.sh`.
Остановить: `bash scripts/stop.sh`. Для установки только коллектора:
`docker compose -f docker-compose.prod.yaml down`. Остановка сохраняет данные;
флаг `down -v` удаляет тома с базами.

## Доступ и эксплуатационные ограничения

- Вход в Moodle и коллектор использует разные аккаунты. Администратор коллектора
  управляет пользователями и данными; обычный пользователь читает и выгружает
  статистику. Интерфейс получает токен на 12 часов. Смена пароля или серверного
  секрета отзывает соответствующие токены. Пароли и хеши не выдаются через API;
  старые открытые записи переводятся в хеш при успешном входе, если хватает бюджета БД.
- Вход ограничен пятью ошибками на email за минуту, 60 попытками с одного
  сетевого источника и 120 на процесс API; одновременно проверяются два пароля.
  При 429 подождите указанное в `Retry-After` время. Счётчики локальны процессу;
  за reverse proxy лимит источника может быть общим для нескольких пользователей.
- Ключ плагина разрешает только отправку событий. Он виден пользователю в браузере
  и не защищает от подделки событий. Сбор не является доказательством действий
  студента: возможны потери и дубли.
- Очередь каждой страницы ограничена 500 событиями или 256 КиБ. Пачка — до 20 событий
  и 48 КиБ; обычная отправка — не чаще раза в секунду на вкладку. При ошибках
  увеличиваются паузы повторов, при переполнении отбрасываются старые события.
  Очередь не переживает закрытие страницы. После трёх ошибок регистрации нужен reload.
- Порог БД по умолчанию — 100 GB выделенного места под данные и индексы. При
  достижении порога новые записи получают 507; при проблемах измерения — 503.
  Чтение и удаление доступны. Это приблизительный бюджет, не квота файловой системы:
  журналы и прочие файлы требуют отдельного запаса. Удаление записей не гарантирует
  уменьшения выделенного места MongoDB. Автоудаления старых событий нет.
- Backend и MongoDB ограничены каждый двумя CPU и 2 ГиБ RAM. Штатный backend
  работает в одном процессе. Таблица показывает до 100 пачек на страницу; экспорт
  выгружает все записи по фильтрам. Разрешён один экспорт на процесс, до пяти минут;
  при 429 повторите запрос позднее. Большой файл в интерфейсе занимает память
  браузера администратора: используйте узкие фильтры или потоковый HTTP-клиент.
- Для разных Moodle используйте отдельные коллекторы и базы. ФИО, email и полный
  URL сохраняются; учитывайте это при выборе доступа и срока хранения. Исторические
  HTML-поля автоматически не удаляются; прямой `mongo_export.sh` может включить их.
- `.env`, ZIP-архивы, кэши, сборки и тестовые отчёты не коммитятся. Trace теста может
  содержать пароли и токены — не публикуйте его вместе с данными доступа.

## Частые ошибки

| Симптом | Проверка |
| --- | --- |
| CORS | `MOODLE_URL` должен совпадать с origin открытого Moodle. После изменения примените конфигурацию backend |
| 401 при отправке событий | Совпадение Collection key в Moodle и `COLLECTOR_INGEST_KEY`; затем перезагрузка страниц |
| 401 в интерфейсе | Войдите заново; токен мог истечь или быть отозван |
| 502 после обновления backend | Перезагрузите nginx: `docker compose exec -T frontend nginx -s reload`; для установки только коллектора добавьте `-f docker-compose.prod.yaml` |
| Нет событий | Вход в Moodle, включение плагина, доступность API из браузера, `window.actionCollector.error` и вкладка Network |
| Не подходит пароль после правки `.env` | Изменение файла не сбрасывает пароль существующей учётной записи |

Логи: `docker compose logs --tail=100 backend frontend moodle`.
В режиме только коллектора: `docker compose -f docker-compose.prod.yaml logs --tail=100`.
