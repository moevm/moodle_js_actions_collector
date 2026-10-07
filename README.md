# Moodle JS Actions Collector

## Архитектура

| Модуль | Сервисы | Назначение |
| --- | --- | --- |
| `deploy/collector/` | MongoDB, backend, frontend | Приём и просмотр событий |
| `deploy/moodle/` | MariaDB, Moodle | Локальный Moodle с демонстрационным курсом |
| Будущий тестовый модуль | Пока отсутствует | Отдельный контейнер для smoke-тестов |

Корневой `docker-compose.yaml` включает два независимых модуля. Коллектор
и Moodle используют разные сети и тома. Браузер отправляет события на API
коллектора через frontend, поэтому Moodle не требует связи с его базой.


## Первый запуск из чистого клона

```bash
bash scripts/start.sh
```

Скрипт создаёт `.env` из `.env.example`, если его нет, собирает образы и
ожидает готовности сервисов. Основной `client/Dockerfile` собирает Vue из
исходников через `npm ci`. `client/dist` для этого не требуется.
Первая сборка скачивает зависимости; повторный запуск использует Docker cache.

Адреса и пароли по умолчанию:

| Сервис | Адрес | Логин | Пароль |
| --- | --- | --- | --- |
| Moodle, администратор | http://localhost:18082 | `admin` | `AdminLocal123!` |
| Moodle, студент | http://localhost:18082 | `student` | `StudentLocal123!` |
| Moodle, преподаватель | http://localhost:18082 | `teacher` | `TeacherLocal123!` |
| Статистика | http://localhost:18081 | `collector@example.com` | `CollectorLocal123!` |
| Документация API | http://localhost:18080/docs | — | — |

Значения настраиваются в `.env`. Пароли пользователей создаются при первой
инициализации; изменение `.env` не меняет пароли уже существующих аккаунтов.
Порты публикуются только на `127.0.0.1`. Для изменения порта Moodle нужно
согласованно изменить `MOODLE_PORT` и `MOODLE_URL`; для frontend —
`COLLECTOR_PORT` и `COLLECTOR_API_URL`. `MOODLE_URL` также задаёт CORS origin.
API URL должен быть доступен браузеру, это не внутреннее имя Docker-сервиса.
Не меняйте `COMPOSE_PROJECT_NAME` существующего стенда: другое имя выберет
другие volumes и будет выглядеть как новая пустая установка.

## Повторный запуск без сборки и скачивания

```bash
bash scripts/start-local.sh
```

Требует уже собранных образов. Этот режим не применяет изменения исходников
backend, frontend и `collector.js` к образам. Для этого нужна пересборка.
В `docker-compose.override.yaml` сохранены монтирования исправленных `seed.php`
и Moodle callback, чтобы продолжал работать ранее развёрнутый стенд.
При сборке нового Moodle-образа эти файлы уже входят в образ.

## Готовый frontend: дополнительный локальный вариант

В предоставленном архиве есть `client/dist`, но он **не коммитится в Git**.
Он нужен только как резервный вариант при проблемах скачивания npm-зависимостей.
В чистом клоне сначала используйте обычную сборку из исходников.

Если `client/dist/index.html` присутствует:

```bash
docker compose -f docker-compose.yaml -f docker-compose.override.yaml \
  -f docker-compose.prebuilt.yaml build --pull=false frontend
bash scripts/start-local.sh
```

Используется `client/Dockerfile.prebuilt`: npm не запускается, требуется локальный
образ `nginx:1.28-alpine` или доступ к его скачиванию. Backend и Moodle должны
быть ранее собраны. Готовый `dist` — снимок frontend; после изменения Vue-кода
он не обновляется автоматически. Основной CI всегда собирает из исходников.

## Ручная проверка

1. Войти в Moodle как `student`, открыть **Collector Demo Course**.
2. Открыть **Reading and scrolling**, прокрутить страницу и скопировать текст.
3. Открыть **Paste and submit your solution**, вставить текст и сохранить ответ.
4. Открыть **Simple quiz: 2 + 2**, начать попытку, ответить `4`, завершить тест.
5. Войти как `teacher` или `admin`, посмотреть сдачи и результаты.
6. Открыть статистику, войти и обновить таблицу. Проверить появление событий.

Точные ссылки и ID модулей можно получить так:

```bash
docker compose exec moodle cat /var/www/moodledata/demo.json
```

Сборщик подключается Moodle-плагином `local_actioncollector`: контекст пользователя
передаётся сервером без чтения страницы профиля. Отслеживаются открытие/закрытие
страницы, видимость вкладки, прокрутка, нажатия, copy/paste/contextmenu и некоторые
клавиатурные сочетания. Поддержаны same-origin iframe редактора TinyMCE.
Значения полей и содержимое буфера обмена в события не передаются. При этом
сохраняется очищенный снимок HTML страницы, который может содержать личные данные.

Исправленный seed использует API банка вопросов Moodle и восстанавливает
утраченную связь категории у вопросов демотеста. Вопросы, версии и попытки
при этом не удаляются.

## Остановка, статус и логи

```bash
bash scripts/stop.sh
docker compose ps -a
docker compose logs --tail=100 moodle backend frontend
```

Остановка сохраняет volumes. Для обновления образов без удаления данных:

```bash
bash scripts/start.sh
```

**`docker compose down -v` удаляет базы и файлы Moodle. Для обычного обновления
эту команду использовать не нужно.**

Экспорт активности без записей паролей пользователей:

```bash
bash mongo_export.sh
```

Результат сохраняется в игнорируемой папке `exports/`; это экспорт JSON,
а не полный резервный снимок всех данных Moodle и MongoDB.

## Коллектор отдельно

```bash
[ -f .env ] || cp .env.example .env
docker compose -f docker-compose.prod.yaml up -d --build --wait --wait-timeout 900
```

Или `bash init-deploy.sh` — совместимый вход для этой команды, без удаления томов.
Имя `prod` означает состав сервисов «только коллектор», а не готовность к
публичному продакшену. Для подключения внешнего Moodle отдельно устанавливаются
плагин и `collector.js`, настраиваются адрес API и CORS origin. HTTPS, доступ
к API и ограничения доступа требуют отдельной настройки.

## Тесты и CI

Существующие backend unit-тесты:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
python -m pytest -q server/tests
```

