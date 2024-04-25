# mse1h2024-moodle

## Сборщик активности moodle

### Итерация 3
1. [Презентация с результатами итерации](https://github.com/moevm/mse1h2024-moodle/wiki/Итерация3#результаты-итерации#презентация)
2. [Подробный план итерации](https://github.com/moevm/mse1h2024-moodle/wiki/Итерация4#план-на-итерацию-4)
3. [Скринкаст с демонстрацией фич](https://github.com/moevm/mse1h2024-moodle/wiki/Итерация3#результаты-итерации#скринкаст-с-демонстрацией-фич)

### Итерация 2
1. [Презентация с результатами итерации](https://github.com/moevm/mse1h2024-moodle/wiki/Итерация2#презентация)
2. [Скринкаст с демонстрацией фич](https://github.com/moevm/mse1h2024-moodle/wiki/Итерация2#скринкаст-с-демонстрацией-фич)

Инструкция для работы с программой:

**Варинт 1.** Основной (с помощью которого можно отследить весь функционал собираемой статистики с moevm) - не поднимается moodle и mariadb - порты оставлены открытыми, чтобы можно было отправлять данные статистики с moevm
1. Для запуска версии проекта необходимо собрать проект с помощью команды `docker-compose build`
2. Далее необходимо поднять контейнеры с помощью команды `docker compose -f .\docker-compose.prod.yaml up`
3. Убедиться, что все контейнеры подняты и по адресу `http://localhost:8081` открывается веб приложение
4. Войти под правами администратора в веб приложение: login - `ivan@mail.ru`,  password - `bhewrtfm3klmt3`
5. Убедиться, что на главное странице просмотра статистики отображены 3 записи - будет означать, что корректно собрана статистика
6. Открыть в браузере https://e.moevm.info/
7. Перейти в панель исследования элемента ([инструкции для разных браузеров](https://www.businessinsider.com/guides/tech/how-to-inspect-element)), открыть панель console
8. Открыть файл moodle_stat_tracker.html
9. Скопировать из него содержимое, удалив при этом все тэги script (их должно быть в файле 4 штуки) - шаг добавлен временно, пока не проверерно, что все корректно работает с помощью вставки в админскую панель в moevm, если будет необходимо добавим временно отдельный файл без тэгов
10. При первом запуске или если еще никгда не выполнялось далее в панели "Исследование элемента" в браузере разрешить копирование кода с помощью команды `allow paste`
11. После чего скопировать туда скрипт и подтвердить выполненине, нажав кнопку "Enter"
12. Если выполненные на странице действия инициировали переход на другую страницу повторить действия 7-9, 11
13. Вернуться на страницу веб-приложения, обновить страницу статистики и убедиться, что все действия, выполненные Вам добалены в список
    
**Вариант 2.** Отладочный
1. Для запуска версии проекта необходимо собрать проект с помощью команды `docker-compose build`, после чего поднять его с помощью команды `docker-compose up`
2. Далее необходимо запустить moodle по адресу `http://localhost`
3. В moodle необходимо авторизоваться с использованием `user = "user", password = "bitnami"`
4. Далее в соответствие с  инструкцией "Подключение" ниже необходимо вставить скрипт из ветки `#137-local-moodle-tracker` для отслеживания действий пользователей, не забыть подтвердить вставку
5. Далее необходимо запустить web-приложение с по адресу `http://localhost:8081`
6. В панели авторизации можно ввести любые данные (в рамках текущей итерации по договоренности с заказчиком авторизация не была реализована)
7. В главном окне веб приложения отобразится собранная статистика

Для проверки работы с бд можно воспользоваться API через swagger по адресу: `http://localhost:8080/docs`




### Подключение

Для того, чтобы подключить отслеживание действий на странице, необходимо:
1. Войти в moodle в учетную запись администратора 
2. Перейти во вкладку администрирования сайта ("Site administration")
3. Выбрать раздел "Внешний вид"("Appearance")
4. Выбрать пункт "Дополнительный HTML"("Additional HTML")
5. Вставить в окно `When BODY is opened` код из файла `moodle_stat_tracker.html`
6. В самом низу страницы нажать кнопку сохранения изменений

С этого момента сборщик активности работает и отслеживает действия всех пользователей на странице.

### Конфигурация подключенного скрипта

```html
<script type="module">
    var interactions = new Interactor({
        trackAll: false,
        numberActionsToSend: 5,
        trackPagePresence: true,
        interactions: true,
        interactionElement: ["A", "BUTTON", "TEXTAREA", "INPUT"],
        interactionEvents: ["mousedown", "copy", "paste"],
        conversions: true,
        conversionElement: "conversion",
        conversionEvents: ["mouseup", "touchend"],
        endpoint: 'http://localhost:8080/api/statistics',
        async: true,
        debug: false
    });
</script>
```

Настройка происходит с помощью изменения значений в полях куска кода трекера, который расположен выше.

 - `trackAll` $-$ при установке значения `true` будет отслеживать любое взаимодействие со страницей.
 - `numberActionsToSend` $-$ Определяет число действий пользователя которые нужно отправлять за итерацию. По умолчанию отсылается по 5 действий пользователя, но можно изменить это значение.
 - `trackPagePresence` $-$ при установке значения `true` будет отслеживать переход с отслеживаемой вкладки на другую.
 - `interactionElement` $-$ определяет элементы которые необходимо отслеживать. Для установки нужно внутри квадратных скобок написать название элемента большими буквами в кавычках. (Например
 `interactionElement: ["DIV"]`, будет отслеживать любое взамодействие с элементами `div`). По умолчанию отслеживаются взаимодействия с элементами `A`, `BUTTON`, `TEXTAREA`, `INPUT`. 
 - `interactionEvents` $-$ определяет действия которые нужно отслеживать (нажатие мыши, отпускание мыши, клик мыши и т.д.). По умолчанию будет использоваться нажатие мыши, копирование в буфер обмена и вставка из буфера обмена. Значения внутри квадратных скобок должны быть написаны строчными буквами в кавычках, как это показано выше.
 - `endpoint` $-$ определяет куда будут отправлены результаты. По умолчанию там будет находится сервер приложения, но при необходимости можно изменить. Нужно лишь прописать путь куда должны отправляться данные.
 - `debug` $-$ необходимо лишь для дальнейшей разработки. По умолчанию будет `false`.

В ветке `main` находится скрипт, работающий на e.moevm.info

В ветке `#137-local-moodle-tracker` находится версия скрипта для работы с локальной чистой версией moodle.

### Запуск тестирования Selenium

Инструкция по запуску тестирования(на текущий момент тестирование локальное): 
- Открыв в терминале папку `client`, необходимо с помощью `npm install` подтянуть новые библиотеки
- Перед этим очистить volumes, удалить старые образы, если проект не собирался с новой версией

`docker rm ID_or_Name ID_or_Name` удаление контейнера, для возможности удаления образов и volumes

`docker rmi` удаление образов, указать название

`docker volume rm Name` удаление volumes

- Запустить версию проекта, необходимо собрать проект с помощью команды `docker-compose build`
- Далее необходимо поднять контейнеры с помощью команды `docker compose -f .\docker-compose.prod.yaml up`
- Проверить, что в системе установлен Nodejs

`node -v`

- Если Nodejs не установлен, то поставить с помощью команд

`sudo apt install nodejs` для Ubuntu

- Далее в терминале своей системы перейти в папку проекта `client/src/test`
- Запуск тестирования с помощью команды `node test-selenium.js`
- По окончанию тестирования в папке появится файл `test.txt` - логирование тестирования

Успешное прохождение тестов - отсуствие в файле логирования тестирования сообщений с флагом ERROR.
