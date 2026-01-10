from time import time

from aiofiles import open as aiopen

from bot import LOGGER, user_data
from bot.core.config_manager import Config
from bot.core.telegram_manager import TgClient
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.ext_utils.db_handler import database
from bot.helper.ext_utils.status_utils import get_readable_time
from bot.helper.telegram_helper.message_utils import delete_message, send_message


@new_task
async def start(_, message):
    if len(message.command) > 1:
        userid = message.from_user.id
        input_ = message.command[1]
        if input_ == "premium":
            Config.PAID_CHANNEL_ID = 0
            Config.PAID_CHANNEL_LINK = ""
            await send_message(message, "Premium mode enabled!")
    else:
        await send_message(message, "Bot Started!")


@new_task
async def ping(_, message):
    start_time = time()
    reply = await send_message(message, "Pong!")
    end_time = time()
    await reply.edit(
        f"Pong! {get_readable_time(end_time - start_time)}",
    )


@new_task
async def log(_, message):
    await send_message(message, "Log File sent!")
