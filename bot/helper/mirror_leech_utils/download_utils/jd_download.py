import asyncio
from time import time

from bot import LOGGER, task_dict, task_dict_lock
from bot.core.jdownloader_booter import jdownloader
from bot.helper.ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
)
from bot.helper.mirror_leech_utils.status_utils.jd_status import JDownloaderStatus
from bot.helper.telegram_helper.message_utils import (
    send_message,
    send_status_message,
)


async def add_jd_download(listener, path):
    msg, button = await stop_duplicate_check(listener)
    if msg:
        await send_message(listener.message, msg, button)
        return

    check, _, _, _ = await check_running_tasks(listener)
    if check:
        return

    try:
        await jdownloader.device.linkgrabber.add_links(
            [{"autostart": True, "links": listener.link, "destinationFolder": path}]
        )
    except Exception as e:
        LOGGER.error(f"JDownloader Error: {e}")
        await send_message(listener.message, f"JDownloader Error: {e}")
        return

    await asyncio.sleep(1)
    LOGGER.info(f"JDownloader Collecting Data: {listener.link}")
    while await jdownloader.device.linkgrabber.is_collecting():
        await asyncio.sleep(0.5)
    LOGGER.info(f"JDownloader Finished Collecting Data: {listener.link}")

    start_time = time()
    online_packages = []
    corrupted_packages = []

    while time() - start_time < 60:
        packages = await jdownloader.device.linkgrabber.query_packages(
            [
                {
                    "name": True,
                    "saveTo": True,
                    "bytesTotal": True,
                    "childCount": True,
                    "status": True,
                }
            ]
        )
        if packages:
            for pack in packages:
                if pack.get("saveTo") == path:
                    if pack.get("status") == "Offline":
                        corrupted_packages.append(pack.get("name"))
                    else:
                        online_packages.append(pack)
            if online_packages:
                break
        await asyncio.sleep(1)

    if corrupted_packages and not online_packages:
        await send_message(
            listener.message,
            f"JDownloader Error: {corrupted_packages} are offline!",
        )
        return

    if not online_packages:
        await send_message(listener.message, "JDownloader Error: No packages found!")
        return

    pack_ids = [pack.get("uuid") for pack in online_packages]
    await jdownloader.device.linkgrabber.move_to_downloadlist(pack_ids, [])

    await listener.on_download_start()
    if listener.multi <= 1:
        await send_status_message(listener.message)

    async with task_dict_lock:
        task_dict[listener.mid] = JDownloaderStatus(listener, listener.mid, "dl")
