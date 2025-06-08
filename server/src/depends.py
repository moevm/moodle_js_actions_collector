import os
import motor.motor_asyncio as aio_motor
from dotenv import load_dotenv

from src.core.modules.database.statistics import MongoStatisticRepo, MongoPageRepo
from src.core.modules.database.user import MongoUserRepo
from src.core.modules.service.authorization import AuthService
from src.core.modules.service.statistics import StatisticsService
from src.core.modules.service.user import UserService


load_dotenv()

user = os.getenv('MONGO_INITDB_ROOT_USERNAME')
password = os.getenv('MONGO_INITDB_ROOT_PASSWORD')
dbname = os.getenv('MONGO_INITDB_DATABASE')

client = aio_motor.AsyncIOMotorClient(f'mongodb://{user}:{password}@mongodb:27017/?authMechanism=DEFAULT')
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
