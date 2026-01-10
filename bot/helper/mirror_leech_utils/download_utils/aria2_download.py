from asyncio import sleep

from bot import LOGGER, aria2_options, task_dict, task_dict_lock
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.ext_utils.task_manager import check_running_tasks, stop_duplicate_check
from bot.helper.mirror_leech_utils.status_utils.aria2_status import Aria2Status
from bot.helper.telegram_helper.message_utils import (
    delete_message,
    send_message,
    send_status_message,
)

from . import Aria2Handle


async def add_aria2_download(listener, dpath, header, ratio, seed_time):
    a2c_opt = {**aria2_options}
    [
        a2c_opt.pop(k)
        for k in aria2_options
        if k in Config.ARIA2_FILE_SELECTION_OPTION.lower().split(", ")
    ]
    a2c_opt["dir"] = dpath
    if listener.name:
        a2c_opt["out"] = listener.name
    if header:
        a2c_opt["header"] = header
    if ratio:
        a2c_opt["seed-ratio"] = ratio
    if seed_time:
        a2c_opt["seed-time"] = seed_time
    if "bittorrent" in a2c_opt and not listener.select:
        a2c_opt.pop("bittorrent")

    msg, button = await stop_duplicate_check(listener)
    if msg:
        await send_message(listener.message, msg, button)
        return

    check, _, _, _ = await check_running_tasks(listener)
    if check:
        return

    try:
        download = await Aria2Handle.addUri([listener.link], a2c_opt)
    except Exception as e:
        LOGGER.error(f"Aria2c Error: {e}")
        await send_message(listener.message, f"Aria2c Error: {e}")
        return

    if download.get("error"):
        LOGGER.error(f"Aria2c Error: {download['error']}")
        await send_message(listener.message, f"Aria2c Error: {download['error']}")
        return

    gid = download["gid"]
    async with task_dict_lock:
        task_dict[listener.mid] = Aria2Status(listener, gid, "dl")

    if listener.select:
        if "bittorrent" in download:
            if not is_metadata(download):
                await listener.on_download_start()
                if listener.multi <= 1:
                    await send_status_message(listener.message)
            else:
                LOGGER.info(f"Downloading Metadata: {gid}")
        else:
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)
    else:
        await listener.on_download_start()
        if listener.multi <= 1:
            await send_status_message(listener.message)


def is_metadata(download):
    if download.get("followedBy"):
        return True
    return False
