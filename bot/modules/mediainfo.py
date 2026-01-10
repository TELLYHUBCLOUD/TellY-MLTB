import asyncio
from os import path as ospath

from aiofiles import open as aiopen
from aiofiles.os import remove as aioremove

from bot import LOGGER
from bot.core.telegram_manager import TgClient
from bot.helper.aeon_utils.access_check import token_check
from bot.helper.ext_utils.bot_utils import cmd_exec
from bot.helper.ext_utils.telegraph_helper import telegraph
from bot.helper.telegram_helper.message_utils import delete_message, send_message


@new_task
async def mediainfo(_, message):
    if not await token_check(message.from_user, message):
        return
    if not message.reply_to_message:
        await send_message(message, "Reply to a message to get media info!")
        return
    reply_to = message.reply_to_message
    if not reply_to.media:
        await send_message(message, "No media found in the replied message!")
        return

    msg = await send_message(message, "Processing...")

    try:
        file_path = await reply_to.download()

        stdout, stderr, _ = await cmd_exec(
            ["mediainfo", file_path]
        )

        if not stdout:
            await delete_message(msg)
            await send_message(message, "Failed to get mediainfo!")
            return

        link = await telegraph.create_page(
            title="Media Info",
            content=stdout.replace("\n", "<br>"),
        )

        await delete_message(msg)
        await send_message(
            message,
            f"<b>Media Info:</b> <a href='{link}'>Click Here</a>",
        )

    except Exception as e:
        LOGGER.error(f"MediaInfo Error: {e}")
        await delete_message(msg)
        await send_message(message, f"Error: {e}")
    finally:
        if file_path and ospath.exists(file_path):
            await aioremove(file_path)
