import os
from urllib.parse import quote_plus
import motor.motor_asyncio as aio_motor
from dotenv import load_dotenv

from src.core.modules.database.statistics import MongoStatisticRepo, MongoPageRepo
from src.core.modules.database.user import MongoUserRepo
from src.core.modules.service.authorization import AuthService
from src.core.modules.service.statistics import StatisticsService
from src.core.modules.service.user import UserService


load_dotenv()

user = os.getenv('MONGODB_ROOT_USER')
password = os.getenv('MONGODB_ROOT_PASSWORD')
dbname = os.getenv('MONGODB_DATABASE')

uri = os.getenv('MONGODB_URI') or (
    f'mongodb://{quote_plus(user or "")}:{quote_plus(password or "")}@mongodb:27017/?authSource=admin'
)
client = aio_motor.AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000, tz_aware=False)
db = client[dbname]
user_service = UserService(MongoUserRepo(db))
statistics_service = StatisticsService(MongoStatisticRepo(db), MongoPageRepo(db))
auth_service = AuthService(MongoUserRepo(db))


def get_user_service() -> UserService:
    return user_service


def get_statistics_service() -> StatisticsService:
    return statistics_service


def get_auth_service() -> AuthService:
    return auth_service
