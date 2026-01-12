from asyncio import Lock

from pyrogram import Client, enums
from pyrogram.types import LinkPreviewOptions

from bot import LOGGER

from .config_manager import Config


class TgClient:
    bot = None
    user = None
    NAME = ""
    ID = 0
    IS_PREMIUM_USER = False
    MAX_SPLIT_SIZE = 2097152000
    lock = Lock()

    @classmethod
    async def start_bot(cls):
        cls.bot = Client(
            "aeon",
            Config.TELEGRAM_API,
            Config.TELEGRAM_HASH,
            proxy=Config.TG_PROXY,
            bot_token=Config.BOT_TOKEN,
            workdir=".",
            parse_mode=enums.ParseMode.HTML,
            max_concurrent_transmissions=100,
            max_message_cache_size=15000,
            max_topic_cache_size=15000,
            sleep_threshold=0,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        await cls.bot.start()
        cls.NAME = cls.bot.me.username
        cls.ID = cls.bot.me.id

    @classmethod
    async def start_user(cls):
        if Config.USER_SESSION_STRING:
            try:
                cls.user = Client(
                    "user",
                    Config.TELEGRAM_API,
                    Config.TELEGRAM_HASH,
                    proxy=Config.TG_PROXY,
                    session_string=Config.USER_SESSION_STRING,
                    workdir=".",
                    parse_mode=enums.ParseMode.HTML,
                    no_updates=True,
                    max_concurrent_transmissions=100,
                    max_message_cache_size=15000,
                    max_topic_cache_size=15000,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                await cls.user.start()
                cls.IS_PREMIUM_USER = cls.user.me.is_premium
                if cls.IS_PREMIUM_USER:
                    cls.MAX_SPLIT_SIZE = 4194304000
            except Exception as e:
                LOGGER.error(f"Failed to start user client: {e}")
                Config.USER_SESSION_STRING = ""
                Config.USER_TRANSMISSION = False

    @classmethod
    async def stop(cls):
        await cls.bot.stop()
        if cls.user:
            await cls.user.stop()

    @classmethod
    async def reload(cls):
        await cls.bot.restart()
        if cls.user:
            await cls.user.restart()
