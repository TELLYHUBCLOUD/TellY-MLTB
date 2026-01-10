from bot import LOGGER, task_dict, task_dict_lock
from bot.helper.ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
)
from bot.helper.mirror_leech_utils.status_utils.queue_status import QueueStatus
from bot.helper.telegram_helper.message_utils import (
    send_message,
    send_status_message,
)


async def add_direct_download(listener, path):
    msg, button = await stop_duplicate_check(listener)
    if msg:
        await send_message(listener.message, msg, button)
        return

    check, _, _, _ = await check_running_tasks(listener)
    if check:
        return

    gid = listener.mid
    async with task_dict_lock:
        task_dict[listener.mid] = QueueStatus(listener, gid, "dl")

    from bot.helper.mirror_leech_utils.download_utils.direct_downloader import (
        DirectDownloader,
    )

    directListener = DirectDownloader(listener, path)

    if listener.select:
        LOGGER.info(f"Downloading Metadata: {listener.name}")
        await directListener.download(True)
        return

    await listener.on_download_start()
    if listener.multi <= 1:
        await send_status_message(listener.message)

    await directListener.download(False)
