import asyncio

from bot import LOGGER, task_dict, task_dict_lock
from bot.core.torrent_manager import TorrentManager
from bot.helper.ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
)
from bot.helper.mirror_leech_utils.status_utils.qbit_status import QbittorrentStatus
from bot.helper.telegram_helper.message_utils import (
    send_message,
    send_status_message,
)


async def add_qb_torrent(listener, path, ratio, seed_time):
    msg, button = await stop_duplicate_check(listener)
    if msg:
        await send_message(listener.message, msg, button)
        return

    check, _, _, _ = await check_running_tasks(listener)
    if check:
        return

    try:
        op = await TorrentManager.qbittorrent.torrents_add(
            urls=listener.link,
            save_path=path,
            is_paused=True,
            tags=f"{listener.mid}",
            ratio_limit=ratio,
            seeding_time_limit=seed_time,
            headers=listener.headers,
        )
    except Exception as e:
        LOGGER.error(f"qBittorrent Error: {e}")
        await send_message(listener.message, f"qBittorrent Error: {e}")
        return

    if op.lower() == "ok.":
        tor_info = await TorrentManager.qbittorrent.torrents_info(
            tag=f"{listener.mid}"
        )
        if len(tor_info) == 0:
            while True:
                tor_info = await TorrentManager.qbittorrent.torrents_info(
                    tag=f"{listener.mid}"
                )
                if len(tor_info) > 0:
                    break
                await asyncio.sleep(1)

        tor_info = tor_info[0]
        ext_hash = tor_info.hash
        listener.name = tor_info.name

        async with task_dict_lock:
            task_dict[listener.mid] = QbittorrentStatus(listener, ext_hash, "dl")

        if listener.select:
            await TorrentManager.qbittorrent.torrents_pause(hashes=ext_hash)
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)
            return

        await TorrentManager.qbittorrent.torrents_resume(hashes=ext_hash)
        await listener.on_download_start()
        if listener.multi <= 1:
            await send_status_message(listener.message)
    else:
        await send_message(
            listener.message, "qBittorrent Error: Failed to add torrent!"
        )
