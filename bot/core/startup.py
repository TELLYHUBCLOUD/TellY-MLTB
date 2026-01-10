from asyncio import create_subprocess_exec, create_subprocess_shell, sleep
from os import environ

import aiohttp
from aiofiles import open as aiopen
from aiofiles.os import path as aiopath
from dotenv import load_dotenv

from bot import (
    LOGGER,
    aria2_options,
    drives_ids,
    drives_names,
    excluded_extensions,
    included_extensions,
    index_urls,
    nzb_options,
    qbit_options,
    sabnzbd_client,
)
from bot.helper.ext_utils.db_handler import database

from .config_manager import Config
from .telegram_manager import TgClient
from .torrent_manager import TorrentManager


async def update_qb_options():
    """Updates qBittorrent options either from current preferences or saved configuration."""
    LOGGER.info("Get qBittorrent options from server")
    if not qbit_options:
        opt = await TorrentManager.qbittorrent.app.preferences()
        qbit_options.update(opt)
    if not await aiopath.exists("qbit_options.dict") and await database.get_qbit_data():
        await database.update_qbit_config()
    elif await aiopath.exists("qbit_options.dict"):
        if await database.get_qbit_data():
            await database.update_qbit_config()
        else:
            await database.save_qbit_config()
    elif not await database.get_qbit_data():
        await database.save_qbit_config()


async def update_aria2_options():
    """Updates Aria2c global options either from current settings or saved configuration."""
    LOGGER.info("Get aria2 options from server")
    if not aria2_options:
        op = await TorrentManager.aria2.getGlobalOption()
        aria2_options.update(op)
    if not await aiopath.exists("aria2_options.dict") and await database.get_aria2_data():
        await database.update_aria2_config()
    elif await aiopath.exists("aria2_options.dict"):
        if await database.get_aria2_data():
            await database.update_aria2_config()
        else:
            await database.save_aria2_config()
    elif not await database.get_aria2_data():
        await database.save_aria2_config()


async def update_nzb_options():
    """Updates NZB options from Sabnzbd client configuration."""
    LOGGER.info("Get SABnzbd options from server")
    while True:
        try:
            no = (await sabnzbd_client.get_config())["config"]["misc"]
            nzb_options.update(no)
        except Exception:
            await sleep(0.5)
            continue
        break


async def load_configurations():
    """Loads all necessary configurations for the bot."""
    await ClientSession().close()
    if Config.DATABASE_URL:
        await database.connect()
        await database.update_config()
        await database.load_aria2_config()
        await database.load_qbit_config()
        await database.load_nzb_config()
    else:
        Config.load()
    await update_variables()
    await TgClient.start_bot()
    await TgClient.start_user()
    await TorrentManager.start_aria2()
    await TorrentManager.start_qbittorrent()
    await update_aria2_options()
    await update_qb_options()
    await update_nzb_options()
    process = await create_subprocess_exec(
        "uv",
        "pip",
        "install",
        "-U",
        "truelink",
    )
    await process.wait()
    from truelink import TrueLinkResolver

    from bot.helper.mirror_leech_utils.download_utils.insta_resolver import (
        InstagramResolver,
    )

    _ = TrueLinkResolver()
    TrueLinkResolver.register_resolver("instagram.com", InstagramResolver)

    if not await aiopath.exists(".netrc"):
        async with aiopen(".netrc", "w"):
            pass
    await create_subprocess_shell("chmod 600 .netrc && cp .netrc /root/.netrc")
    LOGGER.info("Bot Started!")


async def update_variables():
    """Updates global variables based on current configuration."""
    Config.load()
    if Config.EXCLUDED_EXTENSIONS:
        fx = Config.EXCLUDED_EXTENSIONS.split()
        for x in fx:
            x = x.lstrip(".")
            excluded_extensions.append(x.strip().lower())

    if Config.INCLUDED_EXTENSIONS:
        fx = Config.INCLUDED_EXTENSIONS.split()
        for x in fx:
            x = x.lstrip(".")
            included_extensions.append(x.strip().lower())
    if Config.GDRIVE_ID:
        drives_names.append("Main")
        drives_ids.append(Config.GDRIVE_ID)
        index_urls.append(Config.INDEX_URL)

    if await aiopath.exists("list_drives.txt"):
        async with aiopen("list_drives.txt", "r+") as f:
            lines = await f.readlines()
            for line in lines:
                temp = line.strip().split()
                drives_ids.append(temp[1])
                drives_names.append(temp[0].replace("_", " "))
                if len(temp) > 2:
                    index_urls.append(temp[2])
                else:
                    index_urls.append("")

    if not Config.AUTHORIZED_CHATS:
        if Config.SUDO_USERS:
            for x in Config.SUDO_USERS.split():
                auth_chats[int(x)] = {"upload": True, "download": True}
        if Config.OWNER_ID:
            auth_chats[Config.OWNER_ID] = {"upload": True, "download": True}
    elif Config.AUTHORIZED_CHATS:
        for x in Config.AUTHORIZED_CHATS.split():
            if "|" in x:
                x, m = x.split("|")
                auth_chats[int(x)] = {
                    "upload": "u" in m,
                    "download": "d" in m,
                }
            else:
                auth_chats[int(x)] = {"upload": True, "download": True}
        if Config.SUDO_USERS:
            for x in Config.SUDO_USERS.split():
                auth_chats[int(x)] = {"upload": True, "download": True}
        if Config.OWNER_ID:
            auth_chats[Config.OWNER_ID] = {"upload": True, "download": True}
