const { Builder, By, until} = require('selenium-webdriver');
const fs = require('fs');
const edge = require('selenium-webdriver/edge');

const driver = new Builder()
    .forBrowser('MicrosoftEdge')
    .setEdgeOptions(new edge.Options().addArguments("--enable-chrome-browser-cloud-management"))
    .build();

let allUsersCount = 0;

async function test(url) {
    const logFilePath = 'test.txt';
    if (fs.existsSync(logFilePath)) {
        fs.unlinkSync(logFilePath);
    }
    const logStream = fs.createWriteStream(logFilePath, { flags: 'a' });
    try {
        await driver.get(url);

        let currentUrl = await driver.getCurrentUrl();
        logStream.write('Open page: ' + currentUrl + '\n');

        const email = 'ivan@mail.ru';
        const password = 'bhewrtfm3klmt3';

        logStream.write('Input email: ' + email + '\n');
        await driver.findElement(By.id("email-input")).sendKeys(email);

        logStream.write('Input password: ' + password + '\n');
        await driver.findElement(By.id("password-input")).sendKeys(password);

        logStream.write('Click on sign in button\n');
        await driver.findElement(By.id('sign-in-button')).click();
        await driver.sleep(100)

        currentUrl = await driver.getCurrentUrl();
        if (currentUrl === 'http://localhost:8081/e.moevm.statistics/statistics') {
            logStream.write('SUCCESS! Sign in was success\n');
            logStream.write('Open page: ' + currentUrl + '\n');
            await testStatisticPage(logStream);
            await testAllUsersPage(logStream);
            await testAddUserPage(logStream);
        }
        else {
            logStream.write('ERROR! Catch error then sign in\n');
        }
    } finally {
        logStream.write('Exit browser\n');
        await driver.quit();
        logStream.end();
    }
}

async function testStatisticPage(logStream) {
    const searchParam = "Беззубов";
    logStream.write('Input search value: ' + searchParam + '\n');
    const inputSearchElement = await driver.findElement(By.id("search-input"));
    await inputSearchElement.sendKeys(searchParam);
    await driver.wait(until.elementLocated(By.className('v-data-table__tr')), 100);
    let elements = await driver.findElements(By.className("v-data-table__tr"));
    let count = elements.length;
    if (count === 2) {
        logStream.write('SUCCESS! Table was filtered correct by search.\n');
    }
    else {
        logStream.write('ERROR! Table was filtered incorrect by search.\n');
    }
    inputSearchElement.clear();

    const startDateParam = "2024-04-24T00:01";
    const endDateParam = "2024-04-24T00:05";
    logStream.write('Start date value: ' + startDateParam + '\n');
    logStream.write('End date value: ' + endDateParam + '\n');
    const startDateElement = await driver.findElement(By.id("start-date"));
    const endDateElement = await driver.findElement(By.id("end-date"));
    await startDateElement.sendKeys(startDateParam);
    await endDateElement.sendKeys(endDateParam);
    await driver.wait(until.elementLocated(By.className("v-data-table-rows-no-data")), 100);
    elements = await driver.findElements(By.className("v-data-table-rows-no-data"));
    if (elements.length) {
        logStream.write('SUCCESS! Table was filtered correct by date\n');
    }
    startDateElement.clear();
    endDateElement.clear();

    logStream.write('Click on graphic button\n');
    await driver.findElement(By.id('graph-button')).click();
    const graphic = await driver.findElement(By.tagName('canvas'));
    if (graphic) {
        logStream.write('SUCCESS! Graphic was displayed\n');
    }
}

async function testAllUsersPage(logStream) {
    await driver.get('http://localhost:8081/e.moevm.statistics/all-users');
    await driver.sleep(100)
    const currentUrl = await driver.getCurrentUrl();
    if (currentUrl === 'http://localhost:8081/e.moevm.statistics/all-users') {
        logStream.write('SUCCESS! Redirect to all users page was correct\n');
        logStream.write('Open page: ' + currentUrl + '\n');
        await driver.wait(until.elementLocated(By.className('v-data-table__tr')), 100);
        let users = await driver.findElements(By.className("v-data-table__tr"));
        allUsersCount = users.length;
        if (allUsersCount === 3) {
            logStream.write('SUCCESS! Users were displayed correct\n');
        }
        else {
            logStream.write('ERROR! Users were displayed incorrect\n');
        }
    }
    else {
        logStream.write('ERROR! Redirect to all users page was incorrect\n');
    }
}

async function testAddUserPage(logStream) {
    await driver.get('http://localhost:8081/e.moevm.statistics/user');
    await driver.sleep(100)
    const currentUrl = await driver.getCurrentUrl();
    if (currentUrl === 'http://localhost:8081/e.moevm.statistics/user') {
        logStream.write('SUCCESS! Redirect to create user page was correct\n');
        logStream.write('Open page: ' + currentUrl + '\n');

        const email = 'test@mail.ru';
        const surname = 'Smirnov';
        const name = 'Ilya';
        const password = '1234';

        logStream.write('Input email: ' + email + '\n');
        await driver.findElement(By.id("email-input")).sendKeys(email);
        logStream.write('Input surname: ' + surname + '\n');
        await driver.findElement(By.id("surname-input")).sendKeys(surname);
        logStream.write('Input name: ' + name + '\n');
        await driver.findElement(By.id("name-input")).sendKeys(name);
        logStream.write('Input password: ' + password + '\n');
        await driver.findElement(By.id("password-input")).sendKeys(password);
        logStream.write('Click on create button\n');
        await driver.findElement(By.id('create-button')).click();
        await driver.sleep(100);
        let alert = await driver.switchTo().alert();
        let alertText = await alert.getText();
        logStream.write('Alert message: ' + alertText + '\n');
        if (alertText === 'Пользователь успешно создан') {
            logStream.write('SUCCESS! User was created\n');
        }
        else {
            logStream.write('Error! User was not created\n');
        }
    }
    else {
        logStream.write('ERROR! Redirect to create user page was incorrect\n');
    }
}

test('http://localhost:8081/');
