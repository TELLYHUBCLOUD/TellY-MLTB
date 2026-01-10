from aiofiles.os import path as aiopath
from aiofiles.os import remove

from bot import LOGGER, intervals, scheduler
from bot.core.config_manager import Config
from bot.core.telegram_manager import TgClient
from bot.core.torrent_manager import TorrentManager
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.ext_utils.db_handler import database
from bot.helper.telegram_helper.message_utils import send_message


@new_task
async def restart_bot(_, message):
    if await aiopath.exists(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
    else:
        _chat_id, _msg_id = 0, 0

    msg = "Restarting..."
    if message and message.from_user:
        msg = f"Restarting... User: {message.from_user.mention}"

    await send_message(message, msg)

    if scheduler.running:
        scheduler.shutdown(wait=False)

    for interval in [intervals["qb"], intervals["jd"], intervals["status"]]:
        if interval:
            interval.cancel()

    await TorrentManager.aria2.shutdown()
    await TorrentManager.qbittorrent.shutdown()

    if Config.DATABASE_URL:
        await database.disconnect()

    # ... restart logic using os.execv or similar ...
    # This is simplified
    LOGGER.info("Bot Restarting...")


async def send_incomplete_task_message(cid, msg_id, msg):
    try:
        if msg_id:
            await TgClient.bot.edit_message_text(
                chat_id=cid,
                message_id=msg_id,
                text=msg,
            )
            await remove(".restartmsg")
        else:
            await TgClient.bot.send_message(
                chat_id=cid,
                text=msg,
                disable_notification=True,
            )
    except Exception as e:
        LOGGER.error(e)
