import argparse
import subprocess
import json
import datetime

class Time(datetime.time):
    def __sub__(self, other):
        x = self.hour * 3600 + self.minute * 60 + self.second
        y = other.hour * 3600 + other.minute * 60 + other.second
        return x-y


def create_links(parser):
    statistics = open("statistics.json", mode="r")
    data = json.load(statistics)
    users_events = data["data"]
    date = list(map(int, parser.date.split('.')[::-1]))
    date = datetime.date(date[0], date[1], date[2])
    start = list(map(int, parser.start.split(':')))
    start = Time(start[0], start[1], 0, 0)
    end = list(map(int, parser.end.split(':')))
    end = Time(end[0], end[1], 0, 0)
    for writes in users_events:
        if writes["student"] != parser.name:
            continue
        for event in writes["actions"]:
            if event["event_type"] == "scroll":
                continue
            date_time = event["timestamp"]["$date"].split("T")
            event_date = list(map(int, date_time[0].split('-')))
            event_date = datetime.date(event_date[0], event_date[1] ,event_date[2])
            if event_date != date:
                continue
            event_time = list(map(int, date_time[1].replace('.', ':').replace('Z', '').split(':')))
            event_time = Time(event_time[0], event_time[1], event_time[2], event_time[3])
            if event_time < start or event_time > end:
                continue
            event_description = event["element_type"] + " " + event["event_type"] + ":"
            time_code = str(event_time - start)
            link = "https://proctoring.moevm.info/teach/" + parser.id + '?webTime=' + time_code + '&screenTime=' + time_code
            print(event_description, link)


def refactor_statistics():
    with open('statistics.json', 'r') as f:
        data = f.read()
        count = data.count('\n')
        data = data.replace('\n', ',\n', count-1)

    with open('statistics.json', 'r+') as f:
        f.writelines(['{', '"data" : [ '])
        f.write(data)
        f.write(']}')

parser = argparse.ArgumentParser(description="Скрипт для генерации ссылок прокторинга на конкретные действия студента")
parser.add_argument("name", help="ИФ студента через нижнее подчеркивание")
parser.add_argument("id", help="id сессии прокторинга")
parser.add_argument("date", help="Дата сессии")
parser.add_argument("start", help="Время начала сессии")
parser.add_argument("end", help="Время окончания сессии")

args = parser.parse_args()
args.name = args.name.replace("_", " ")

subprocess.run("./../mongo_export.sh")

refactor_statistics()
create_links(args)