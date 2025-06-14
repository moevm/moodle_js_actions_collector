db = db.getSiblingDB('moodle-statistics');

// set your users
db.users.insertMany([
    {
        "name": "Иван",
        "surname": "Иванов",
        "lastname": "Иванович",
        "email": "ivan@mail.ru",
        "position": "admin",
        "password": "bhewrtfm3klmt3"
    }
])
