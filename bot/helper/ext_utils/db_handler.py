from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError
from pymongo.server_api import ServerApi

from bot import LOGGER, qbit_options, rss_dict, user_data
from bot.core.config_manager import Config


class DbManager:
    def __init__(self):
        self._err = False
        self.db = None
        self._conn = None
        self._return = True

    async def connect(self):
        try:
            self._conn = AsyncIOMotorClient(
                Config.DATABASE_URL,
                server_api=ServerApi("1"),
                connectTimeoutMS=60000,
                serverSelectionTimeoutMS=60000,
            )
            self.db = self._conn.tellyaeon
            self._return = False
        except PyMongoError as e:
            LOGGER.error(f"Error in DB connection: {e}")
            self._err = True

    async def disconnect(self):
        if self._conn is not None:
            self._conn.close()

    async def update_config(self):
        if self._err or self._return:
            return
        await self.db.config.replace_one(
            {"_id": Config.BOT_TOKEN},
            Config.get_all(),
            upsert=True,
        )

    async def update_aria2(self, key, value):
        if self._err or self._return:
            return
        await self.db.aria2.update_one(
            {"_id": Config.BOT_TOKEN},
            {"$set": {key: value}},
            upsert=True,
        )

    async def update_qb(self, key, value):
        if self._err or self._return:
            return
        await self.db.qb.update_one(
            {"_id": Config.BOT_TOKEN},
            {"$set": {key: value}},
            upsert=True,
        )

    async def update_nzb_config(self):
        if self._err or self._return:
            return
        # Implement update nzb config logic here

    async def update_private_file(self, path):
        if self._err or self._return:
            return
        with open(path, "rb") as f:
            data = f.read()
        await self.db.files.update_one(
            {"_id": Config.BOT_TOKEN},
            {"$set": {path: data}},
            upsert=True,
        )

    async def update_user_data(self, user_id):
        if self._err or self._return:
            return
        if user_id in user_data:
            await self.db.users.replace_one(
                {"_id": user_id},
                user_data[user_id],
                upsert=True,
            )

    async def update_user_doc(self, user_id, key, path=None):
        if self._err or self._return:
            return
        if path:
            with open(path, "rb") as f:
                data = f.read()
            await self.db.users.update_one(
                {"_id": user_id},
                {"$set": {key: data}},
                upsert=True,
            )
        else:
            await self.db.users.update_one(
                {"_id": user_id},
                {"$unset": {key: ""}},
            )

    async def rss_update(self, user_id):
        if self._err or self._return:
            return
        if user_id in rss_dict:
            await self.db.rss.replace_one(
                {"_id": user_id},
                rss_dict[user_id],
                upsert=True,
            )

    async def rss_delete(self, user_id):
        if self._err or self._return:
            return
        await self.db.rss.delete_one({"_id": user_id})

    async def add_incomplete_task(self, cid, link, tag):
        if self._err or self._return:
            return
        await self.db.tasks.insert_one({"cid": cid, "link": link, "tag": tag})

    async def rm_complete_task(self, link):
        if self._err or self._return:
            return
        await self.db.tasks.delete_one({"link": link})

    async def trunc_table(self, name):
        if self._err or self._return:
            return
        await self.db[name].drop()

    async def get_aria2_data(self):
        if self._err or self._return:
            return None
        return await self.db.aria2.find_one({"_id": Config.BOT_TOKEN})

    async def get_qbit_data(self):
        if self._err or self._return:
            return None
        return await self.db.qb.find_one({"_id": Config.BOT_TOKEN})

    async def save_qbit_config(self):
        if self._err or self._return:
            return
        await self.db.qb.replace_one(
            {"_id": Config.BOT_TOKEN},
            qbit_options,
            upsert=True,
        )

    async def update_qbit_config(self):
        if self._err or self._return:
            return
        data = await self.db.qb.find_one({"_id": Config.BOT_TOKEN})
        if data:
            del data["_id"]
            qbit_options.update(data)

    async def save_aria2_config(self):
        if self._err or self._return:
            return
        await self.db.aria2.replace_one(
            {"_id": Config.BOT_TOKEN},
            aria2_options,
            upsert=True,
        )

    async def update_aria2_config(self):
        if self._err or self._return:
            return
        data = await self.db.aria2.find_one({"_id": Config.BOT_TOKEN})
        if data:
            del data["_id"]
            # Implementation to update global aria2 options would go here

    async def load_nzb_config(self):
        if self._err or self._return:
            return
        # Implementation to load nzb config

    async def load_aria2_config(self):
        await self.update_aria2_config()

    async def load_qbit_config(self):
        await self.update_qbit_config()

    async def rss_update_all(self):
        if self._err or self._return:
            return
        for user_id in rss_dict:
            await self.rss_update(user_id)


database = DbManager()
