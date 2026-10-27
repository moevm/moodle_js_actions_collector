from typing import Any

from bson.objectid import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from src.core.modules.database.errors import (
    RepoAlreadyExistsError,
    RepoEmptyDataError,
    RepoNotFoundError,
    RepoProtectedAdminError,
    RepoUserManagementUnavailableError,
)


ADMIN_GUARD_ID = "protected-administrator"
USER_QUERY_TIMEOUT_MS = 10_000


class MongoUserRepo:
    def __init__(self, client: Any) -> None:
        self.client = client
        self._email_index_ready = False

    async def _ensure_email_index(self) -> None:
        if self._email_index_ready:
            return
        try:
            # Also covers existing installations where mongo-init.js never ran.
            # Conflicting legacy data stays intact; only management writes fail.
            await self.client.users.create_index(
                [("email", 1)], unique=True, maxTimeMS=USER_QUERY_TIMEOUT_MS,
            )
        except PyMongoError as error:
            raise RepoUserManagementUnavailableError("Cannot ensure unique user emails") from error
        self._email_index_ready = True

    async def _protected_admin_id(self) -> ObjectId:
        """Choose a permanent anchor shared by API processes, without leases.

        Every deletion/demotion waits for initialization before changing users.
        The unique settings _id and $setOnInsert make competing initializers agree.
        No API path removes or demotes this user, even with other admins.
        """
        settings = self.client.collector_settings
        guard = await settings.find_one({"_id": ADMIN_GUARD_ID}, max_time_ms=USER_QUERY_TIMEOUT_MS)
        if guard is None:
            candidate = await self.client.users.find_one(
                {"position": "admin"}, projection={"_id": 1}, sort=[("_id", 1)],
                max_time_ms=USER_QUERY_TIMEOUT_MS,
            )
            if candidate is None:
                raise RepoUserManagementUnavailableError("No administrator to protect")
            try:
                guard = await settings.find_one_and_update(
                    {"_id": ADMIN_GUARD_ID},
                    {"$setOnInsert": {"user_id": candidate["_id"]}},
                    upsert=True, return_document=ReturnDocument.AFTER,
                    maxTimeMS=USER_QUERY_TIMEOUT_MS,
                )
            except DuplicateKeyError:
                # Some concurrent upserts report a collision instead of retrying.
                guard = await settings.find_one(
                    {"_id": ADMIN_GUARD_ID}, max_time_ms=USER_QUERY_TIMEOUT_MS,
                )
        protected_id = guard.get("user_id") if guard else None
        if not isinstance(protected_id, ObjectId) or await self.client.users.find_one(
            {"_id": protected_id, "position": "admin"}, projection={"_id": 1},
            max_time_ms=USER_QUERY_TIMEOUT_MS,
        ) is None:
            # Never silently choose another anchor after manual DB corruption.
            raise RepoUserManagementUnavailableError("Protected administrator is unavailable")
        return protected_id

    async def get_all_users(self) -> list:
        users = []
        for user in await self.client.users.find().to_list(length=None):
            user['_id'] = str(user['_id'])
            users.append(user)
        return users

    async def get_user(self, user_id: str) -> dict:
        user = await self.client.users.find_one({"_id": ObjectId(user_id)})
        if user:
            user['_id'] = str(user['_id'])
            return user
        raise RepoNotFoundError(f"user with id {user_id} not found")

    async def get_user_by_email(self, email: str) -> dict:
        if not email:
            raise RepoEmptyDataError("invalid email length")
        user = await self.client.users.find_one({"email": email})
        if user:
            user['_id'] = str(user['_id'])
            return user
        raise RepoNotFoundError(f"user with email {email} not found")

    async def add_user(self, user_data: dict) -> dict:
        await self._ensure_email_index()
        try:
            data = dict(user_data)
            result = await self.client.users.insert_one(data)
        except DuplicateKeyError as error:
            raise RepoAlreadyExistsError("User email is already in use") from error
        data['_id'] = str(result.inserted_id)
        return data

    async def update_user(self, user_id: str, data: dict) -> dict:
        if not data:
            raise RepoEmptyDataError("empty request body")
        object_id = ObjectId(user_id)
        if "position" in data and data["position"] != "admin":
            if object_id == await self._protected_admin_id():
                raise RepoProtectedAdminError("The protected administrator cannot be demoted")
        await self._ensure_email_index()
        try:
            user = await self.client.users.find_one_and_update(
                {"_id": object_id}, {"$set": data}, return_document=ReturnDocument.AFTER,
                maxTimeMS=USER_QUERY_TIMEOUT_MS,
            )
        except DuplicateKeyError as error:
            raise RepoAlreadyExistsError("User email is already in use") from error
        if user is None:
            raise RepoNotFoundError(f"user with id {user_id} not found")
        user['_id'] = str(user['_id'])
        return user

    async def replace_password(self, user_id: str, expected: str, replacement: str) -> bool:
        result = await self.client.users.update_one(
            {"_id": ObjectId(user_id), "password": expected}, {"$set": {"password": replacement}},
        )
        return result.modified_count == 1

    async def delete_user(self, user_id: str) -> Any:
        object_id = ObjectId(user_id)
        if object_id == await self._protected_admin_id():
            raise RepoProtectedAdminError("The protected administrator cannot be deleted")
        result = await self.client.users.delete_one({"_id": object_id})
        if result.deleted_count != 1:
            raise RepoNotFoundError(f"user with id {user_id} not found")
        return result
