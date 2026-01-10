from logging import getLogger

from bot import task_dict, task_dict_lock
from bot.helper.ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
)
from bot.helper.mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from bot.helper.telegram_helper.message_utils import (
    send_message,
    send_status_message,
)

LOGGER = getLogger(__name__)


async def add_telegram_download(listener, path):
    msg, button = await stop_duplicate_check(listener)
    if msg:
        await send_message(listener.message, msg, button)
        return

    check, _, _, _ = await check_running_tasks(listener)
    if check:
        return

    async with task_dict_lock:
        task_dict[listener.mid] = TelegramStatus(listener, listener.mid, "dl")

    await listener.on_download_start()
    if listener.multi <= 1:
        await send_status_message(listener.message)

    from bot.helper.mirror_leech_utils.download_utils.telegram_downloader import (
        TelegramDownloader,
    )

    tg_downloader = TelegramDownloader(listener, path)
    await tg_downloader.download()
