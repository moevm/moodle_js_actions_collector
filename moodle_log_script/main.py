import requests
import re

login = ""
passwd = ''

session = requests.Session()
r = session.get("https://e.moevm.info/login/index.php")
cookie = r.cookies.get_dict()
pattern = r'<input type="hidden" name="logintoken" value="\w{32}">'
token = re.findall(pattern, r.text)
token = re.findall(r"\w{32}", token[0])
payload = {'username': login, 'password': passwd, 'anchor': '', 'logintoken': token[0]}
r = session.post("https://e.moevm.info/login/index.php", data=payload)
try:
    sesskey = re.findall('"sesskey":"[a-zA-Z0-9]*"',r.content.decode())[0].split('"')[3]
    print(sesskey)
except Exception as e:
    print(e)
url = f'https://e.moevm.info/report/log/index.php?sesskey={sesskey}&download=csv&id=45&modid=&chooselog=1&logreader=logstore_standard'  # Замените на URL, где находится файл
file_path = 'out.csv'  # Замените на желаемый путь сохранения файла

try:
    print(session.cookies.get_dict())
    response = session.get(url, stream=True, cookies=session.cookies)
    response.raise_for_status()  # Проверяем статус ответа

    with open(file_path, 'wb') as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)

    print(f'Файл успешно загружен и сохранен в {file_path}')

except requests.exceptions.RequestException as e:
    print(f'Ошибка при загрузке файла: {e}')