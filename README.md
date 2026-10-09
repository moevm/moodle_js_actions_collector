# Moodle JS Actions Collector

Локальный стенд для ручной проверки расширенных событий Moodle.
Moodle зафиксирован на **5.0.2 (Build: 20250811)**; версия проверяется при сборке.

## Архитектура

| Модуль | Сервисы | Назначение |
| --- | --- | --- |
| `deploy/collector/` | MongoDB, backend, frontend | Приём и просмотр событий |
| `deploy/moodle/` | MariaDB, Moodle | Локальный Moodle с демонстрационным курсом |
| `deploy/tests/` | Chromium / Playwright, профиль `test` | Сквозные проверки Moodle и доставки событий |

Корневой `docker-compose.yaml` включает три модуля. Коллектор
и Moodle используют разные сети и тома. Браузер отправляет события на API
коллектора через frontend, поэтому Moodle не требует связи с его базой.

## Требования

Docker Engine или Docker Desktop с Docker Compose **2.20+** (поддержка `include`),
Bash и доступ к Docker Hub, GitHub, Debian/Alpine, PyPI и npm при первой сборке.
Команды выполняются из корня проекта. Dockerfile Moodle использует тег `v5.0.2`.
Теги базовых образов фиксируют ветки/версии, но не обеспечивают побайтовую
воспроизводимость: для этого позже нужно закрепить digest всех образов.

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

GitHub Actions запускает backend unit-тесты и сборку Docker из исходников.
Старый Selenium-тест сохранён в `client/src/test/test.mjs` как исторический материал.
Актуальный браузерный модуль — `e2e/`, контейнер описан в `deploy/tests/`.
Он не запускается при обычном `docker compose up`.

На уже работающем локальном стенде:

```bash
bash scripts/test.sh
```

Первый запуск скачивает официальный образ Playwright с Chromium и устанавливает
тестовые зависимости при сборке. Node.js и браузер на компьютере не нужны.
Повторный запуск готового тестового образа без сборки и скачивания:

```bash
bash scripts/test.sh --no-build
```

Проверяются вход с возвратом на исходную страницу, реальные copy/paste,
прокрутка и закрытие страницы, доставка событий через API, вставка в TinyMCE
и сохранение задания, правильное завершение демотеста, вход и таблица статистики.
Сценарии создают события, обновляют ответ студента и добавляют попытку демотеста;
используйте демонстрационный локальный стенд. Базы не очищаются.
Результат команды: `0` при успехе, ненулевой код при сбое.
Отчёт — `reports/e2e/html/index.html`, JUnit — `reports/e2e/junit.xml`;
при ошибке сохраняются скриншот, видео и trace в `reports/e2e/test-results/`.
`reports/` исключён из Git.

Тесты можно выбирать аргументами Playwright:

```bash
bash scripts/test.sh --no-build --grep 'TinyMCE'
```

Тестовый контейнер имеет доступ к обеим Docker-сетям. Внутри него HTTP-прокси
сохраняет настроенные адреса `localhost`, направляя реальные запросы к Moodle,
frontend и backend. Контент, redirect, cookies и Origin не подменяются.
Модуль поддерживает локальные HTTP-адреса `localhost`/`127.0.0.1` текущего стенда;
внешние домены и HTTPS требуют отдельного режима интеграционных тестов.
Подробности модуля: [e2e/README.md](e2e/README.md).

Workflow **Browser smoke tests** запускается вручную через GitHub Actions;
его отчёт сохраняется как artifact. Обычный CI также проверяет сборку тестового
образа. Эти smoke-тесты не доказывают полноту доставки при обрывах сети.

## Ограничения перед продакшеном

Текущая версия рассчитана на локальную ручную проверку. Backend пока хранит
пароли открытым текстом и возвращает их в модели `User`; API пользователей
и статистики не проверяет авторизацию. Перед публикацией нужны хеширование
паролей, авторизация/права, ответы без паролей и защита приёма событий.
Эти изменения не входят в текущую подготовку репозитория.

## Применение архива к существующему репозиторию

Сохраните архив рядом с папкой проекта (`~/moevm`), затем:

```bash
cd ~/moevm
unzip -o moodle_js_actions_collector_playwright.zip
cd moodle_js_actions_collector
bash scripts/prepare-commit.sh
```

Архив не содержит `.git` и `.env`; они остаются на месте. Скрипт переносит старый
`local-test`, прежние Compose/тестовые входы и файлы `Zone.Identifier` в
игнорируемую `.commit-backup/`. Он не останавливает контейнеры и не меняет volumes.

Если эти файлы раньше были отслеживаемыми, уберите локальную конфигурацию
и готовую сборку из индекса (локальные файлы сохранятся):

```bash
git rm --cached --ignore-unmatch .env server/.env packages/statistic/.env
git rm -r --cached --ignore-unmatch client/dist
git add -A
git diff --cached --check
git diff --cached --stat
git ls-files -- '*Zone.Identifier*' '.env' 'server/.env' 'packages/statistic/.env' 'client/dist/*'
```

Последняя команда должна ничего не вывести. Проверьте staged diff перед коммитом.
Удаление секретов из индекса не удаляет их из истории: если реальные пароли уже
публиковались, их нужно заменить. Пример названия коммита:

```bash
git commit -m "Separate collector and local Moodle 5.0.2 deployment"
```

Предыдущие материалы проекта: https://github.com/moevm/mse1h2024-moodle/wiki
