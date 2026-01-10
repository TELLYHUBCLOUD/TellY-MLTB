import asyncio

from aiofiles import open as aiopen
from aiofiles.os import path as aiopath
from aiofiles.os import remove

from bot import (
    DEFAULT_VALUES,
    aria2_options,
    auth_chats,
    drives_ids,
    drives_names,
    excluded_extensions,
    included_extensions,
    index_urls,
    intervals,
    jd_listener_lock,
    nzb_options,
    qbit_options,
    sudo_users,
)
from bot.core.config_manager import Config
from bot.core.jdownloader_booter import jdownloader
from bot.core.startup import update_nzb_options, update_variables
from bot.core.torrent_manager import TorrentManager
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.ext_utils.db_handler import database
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import (
    edit_message,
    send_message,
)


async def get_buttons(key=None, edit_type=None):
    buttons = ButtonMaker()
    if key is None:
        buttons.data_button("Config Variables", "botset var")
        buttons.data_button("Private Files", "botset private")
        buttons.data_button("Qbit/Aria2 Options", "botset aria")
        buttons.data_button("JDownloader Sync", "botset syncjd")
        buttons.data_button("SABnzbd Sync", "botset syncnzb")
        buttons.data_button("Close", "botset close")
        msg = "Bot Settings:"
    elif key == "var":
        for k in list(Config.__annotations__.keys()):
            buttons.data_button(k, f"botset editvar {k}")
        buttons.data_button("Back", "botset back")
        buttons.data_button("Close", "botset close")
        msg = "Config Variables:"
    elif key == "private":
        buttons.data_button(".netrc", "botset editprivate .netrc")
        buttons.data_button("token.pickle", "botset editprivate token.pickle")
        buttons.data_button("accounts.zip", "botset editprivate accounts.zip")
        buttons.data_button("list_drives.txt", "botset editprivate list_drives.txt")
        buttons.data_button("cookies.txt", "botset editprivate cookies.txt")
        buttons.data_button("Back", "botset back")
        buttons.data_button("Close", "botset close")
        msg = "Private Files:"
    elif key == "aria":
        buttons.data_button("Aria2", "botset aria2")
        buttons.data_button("Qbit", "botset qbit")
        buttons.data_button("Back", "botset back")
        buttons.data_button("Close", "botset close")
        msg = "Aria2/Qbit Options:"
    elif key == "aria2":
        for k in list(aria2_options.keys()):
            buttons.data_button(k, f"botset editaria {k}")
        buttons.data_button("Back", "botset aria")
        buttons.data_button("Close", "botset close")
        msg = "Aria2 Options:"
    elif key == "qbit":
        for k in list(qbit_options.keys()):
            buttons.data_button(k, f"botset editqbit {k}")
        buttons.data_button("Back", "botset aria")
        buttons.data_button("Close", "botset close")
        msg = "Qbit Options:"
    elif edit_type == "editvar":
        msg = f"<b>Variable:</b> {key}\n<b>Description:</b> {Config.__annotations__[key]}"
        msg += f"\n\n<b>Current Value:</b> {getattr(Config, key)}"
        buttons.data_button("Edit Value", f"botset editvar {key} edit")
        buttons.data_button("Reset Value", f"botset resetvar {key}")
        buttons.data_button("Back", "botset var")
        buttons.data_button("Close", "botset close")
    elif edit_type == "editprivate":
        msg = f"<b>File:</b> {key}"
        if await aiopath.exists(key):
            msg += "\n\n<b>Exists:</b> True"
        else:
            msg += "\n\n<b>Exists:</b> False"
        buttons.data_button("Edit File", f"botset editprivate {key} edit")
        buttons.data_button("Delete File", f"botset deleteprivate {key}")
        buttons.data_button("Back", "botset private")
        buttons.data_button("Close", "botset close")
    elif edit_type == "editaria":
        msg = f"<b>Option:</b> {key}"
        msg += f"\n\n<b>Current Value:</b> {aria2_options[key]}"
        buttons.data_button("Edit Value", f"botset editaria {key} edit")
        buttons.data_button("Back", "botset aria2")
        buttons.data_button("Close", "botset close")
    elif edit_type == "editqbit":
        msg = f"<b>Option:</b> {key}"
        msg += f"\n\n<b>Current Value:</b> {qbit_options[key]}"
        buttons.data_button("Edit Value", f"botset editqbit {key} edit")
        buttons.data_button("Back", "botset qbit")
        buttons.data_button("Close", "botset close")
    return msg, buttons.build_menu(2)


async def update_buttons(message, key=None, edit_type=None):
    msg, buttons = await get_buttons(key, edit_type)
    await edit_message(message, msg, buttons)


async def edit_variable(_, message, pre_message, key):
    handler_dict[message.chat.id] = False
    value = message.text
    if key == "RSS_DELAY":
        value = int(value)
        if intervals["rss"]:
            intervals["rss"].cancel()
    elif key == "RSS_SIZE_LIMIT":
        value = int(value)
    elif key == "TORRENT_TIMEOUT":
        value = int(value)
        downloads = await database.db.aria2.find_one({"_id": Config.BOT_TOKEN})
        if downloads:
            downloads = downloads["bt-stop-timeout"]
            await TorrentManager.change_aria2_option("bt-stop-timeout", f"{value}")
    elif key == "LEECH_SPLIT_SIZE":
        value = int(value)
    elif key == "BASE_URL":
        await TorrentManager.aria2.changeGlobalOption(
            {"rpc-allow-origin-all": "true"}
        )
    elif key == "EXCLUDED_EXTENSIONS":
        fx = value.split()
        excluded_extensions.clear()
        excluded_extensions.extend(["aria2", "!qB"])
        for x in fx:
            x = x.lstrip(".")
            excluded_extensions.append(x.strip().lower())
    elif key == "INCLUDED_EXTENSIONS":
        fx = value.split()
        included_extensions.clear()
        for x in fx:
            x = x.lstrip(".")
            included_extensions.append(x.strip().lower())
    elif key == "GDRIVE_ID":
        if drives_names and drives_names[0] == "Main":
            drives_ids[0] = value
        else:
            drives_names.insert(0, "Main")
            drives_ids.insert(0, value)
    elif key == "INDEX_URL":
        if drives_names and drives_names[0] == "Main":
            index_urls[0] = value
        else:
            index_urls.insert(0, value)
    elif key == "AUTHORIZED_CHATS":
        aid = value.split()
        auth_chats.clear()
        if Config.SUDO_USERS:
            for x in Config.SUDO_USERS.split():
                auth_chats[int(x)] = {"upload": True, "download": True}
        if Config.OWNER_ID:
            auth_chats[Config.OWNER_ID] = {"upload": True, "download": True}
        for x in aid:
            if "|" in x:
                x, m = x.split("|")
                auth_chats[int(x)] = {
                    "upload": "u" in m,
                    "download": "d" in m,
                }
            else:
                auth_chats[int(x)] = {"upload": True, "download": True}
    elif key == "SUDO_USERS":
        sid = value.split()
        sudo_users.clear()
        if Config.OWNER_ID:
            sudo_users.append(Config.OWNER_ID)
            auth_chats[Config.OWNER_ID] = {"upload": True, "download": True}
        for x in sid:
            sudo_users.append(int(x))
            auth_chats[int(x)] = {"upload": True, "download": True}
    elif key == "YT_DLP_OPTIONS":
        value = eval(value)
    Config.set(key, value)
    await database.update_config()
    if (
        key in ["RSS_DELAY", "RSS_SIZE_LIMIT", "TORRENT_TIMEOUT"]
        or key == "BASE_URL"
    ):
        pass
    else:
        await update_variables()
    await delete_message(message)
    await update_buttons(pre_message, "var")


async def edit_aria(_, message, pre_message, key):
    handler_dict[message.chat.id] = False
    value = message.text
    aria2_options[key] = value
    await database.update_aria2(key, value)
    await delete_message(message)
    await update_buttons(pre_message, "aria2")


async def edit_qbit(_, message, pre_message, key):
    handler_dict[message.chat.id] = False
    value = message.text
    qbit_options[key] = value
    await database.update_qb(key, value)
    await delete_message(message)
    await update_buttons(pre_message, "qbit")


async def update_private_file(_, message, pre_message):
    handler_dict[message.chat.id] = False
    if not message.document:
        await delete_message(message)
        return
    file_name = message.document.file_name
    await message.download(file_name=file_name)
    if file_name == "accounts.zip":
        if await aiopath.exists("accounts"):
            await remove("accounts")
        await create_subprocess_shell(
            "7z x accounts.zip -oaccounts -aoa -bso0 -bsp0"
        )
        await create_subprocess_shell("chmod 777 accounts")
        await remove("accounts.zip")
    elif file_name == "list_drives.txt":
        drives_ids.clear()
        drives_names.clear()
        index_urls.clear()
        if Config.GDRIVE_ID:
            drives_names.append("Main")
            drives_ids.append(Config.GDRIVE_ID)
            index_urls.append(Config.INDEX_URL)
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
    elif file_name in [".netrc", "netrc"]:
        await create_subprocess_shell("chmod 600 .netrc && cp .netrc /root/.netrc")
    await database.update_private_file(file_name)
    await delete_message(message)
    await update_buttons(pre_message, "private")


async def event_handler(client, query, pfunc, r_func, document=False):
    chat_id = query.message.chat.id
    handler_dict[chat_id] = True
    start_time = time()

    async def event_filter(_, __, event):
        if document:
            return bool(
                event.document
                and event.chat.id == chat_id
                and event.from_user.id == query.from_user.id
            )
        return bool(
            event.text
            and event.chat.id == chat_id
            and event.from_user.id == query.from_user.id
        )

    handler = client.add_handler(
        MessageHandler(pfunc, create(event_filter)),
        group=-1,
    )
    while handler_dict[chat_id]:
        await asyncio.sleep(0.5)
        if time() - start_time > 60:
            handler_dict[chat_id] = False
            await r_func()
    client.remove_handler(*handler)


@new_task
async def edit_bot_settings(client, query):
    data = query.data.split()
    message = query.message
    if data[1] == "close":
        handler_dict[message.chat.id] = False
        await query.answer()
        await delete_message(message.reply_to_message)
        await delete_message(message)
    elif data[1] == "back":
        handler_dict[message.chat.id] = False
        await query.answer()
        key = data[2] if len(data) == 3 else None
        if key is None:
            await update_buttons(message)
        else:
            await update_buttons(message, key)
    elif data[1] in ["var", "private", "aria", "aria2", "qbit"]:
        await query.answer()
        await update_buttons(message, data[1])
    elif data[1] == "syncjd":
        if jd_listener_lock.locked():
            await query.answer(
                "Synchronization in progress. Please wait!", show_alert=True
            )
            return
        await query.answer(
            "Synchronization Started. JDownloader will get restarted. It takes up to 10 sec!",
            show_alert=True,
        )
        await sync_jdownloader()
    elif data[1] == "syncnzb":
        await query.answer(
            "Synchronization Started. It takes up to 2 sec!",
            show_alert=True,
        )
        nzb_options.clear()
        await update_nzb_options()
    elif data[1] == "editvar":
        await query.answer()
        if len(data) == 4:
            handler_dict[message.chat.id] = False
            await update_buttons(message, data[2], "editvar")
            pfunc = partial(edit_variable, pre_message=message, key=data[2])
            r_func = partial(update_buttons, message, "var")
            await event_handler(client, query, pfunc, r_func)
        else:
            await update_buttons(message, data[2], "editvar")
    elif data[1] == "editprivate":
        await query.answer()
        if len(data) == 4:
            handler_dict[message.chat.id] = False
            await update_buttons(message, data[2], "editprivate")
            pfunc = partial(update_private_file, pre_message=message)
            r_func = partial(update_buttons, message, "private")
            await event_handler(client, query, pfunc, r_func, document=True)
        else:
            await update_buttons(message, data[2], "editprivate")
    elif data[1] == "editaria":
        await query.answer()
        if len(data) == 4:
            handler_dict[message.chat.id] = False
            await update_buttons(message, data[2], "editaria")
            pfunc = partial(edit_aria, pre_message=message, key=data[2])
            r_func = partial(update_buttons, message, "aria2")
            await event_handler(client, query, pfunc, r_func)
        else:
            await update_buttons(message, data[2], "editaria")
    elif data[1] == "editqbit":
        await query.answer()
        if len(data) == 4:
            handler_dict[message.chat.id] = False
            await update_buttons(message, data[2], "editqbit")
            pfunc = partial(edit_qbit, pre_message=message, key=data[2])
            r_func = partial(update_buttons, message, "qbit")
            await event_handler(client, query, pfunc, r_func)
        else:
            await update_buttons(message, data[2], "editqbit")
    elif data[1] == "resetvar":
        await query.answer()
        expected_type = type(getattr(Config, data[2]))
        if expected_type is bool:
            value = False
        elif expected_type is int:
            value = 0
        elif expected_type is str:
            value = ""
        elif expected_type is list:
            value = []
        elif expected_type is dict:
            value = {}
        if data[2] in DEFAULT_VALUES:
            value = DEFAULT_VALUES[data[2]]
        elif data[2] == "EXCLUDED_EXTENSIONS":
            excluded_extensions.clear()
            excluded_extensions.extend(["aria2", "!qB"])
        elif data[2] == "INCLUDED_EXTENSIONS":
            included_extensions.clear()
        elif data[2] == "TORRENT_TIMEOUT":
            await TorrentManager.change_aria2_option("bt-stop-timeout", "0")
            await database.update_aria2("bt-stop-timeout", "0")
        elif data[2] == "BASE_URL":
            await TorrentManager.aria2.changeGlobalOption(
                {"rpc-allow-origin-all": "false"}
            )
        Config.set(data[2], value)
        await database.update_config()
        if (
            data[2] in ["RSS_DELAY", "RSS_SIZE_LIMIT", "TORRENT_TIMEOUT"]
            or data[2] == "BASE_URL"
        ):
            pass
        else:
            await update_variables()
        await update_buttons(message, "var")
    elif data[1] == "deleteprivate":
        await query.answer()
        await remove(data[2])
        await database.update_user_doc(Config.BOT_TOKEN, data[2])
        if data[2] == "list_drives.txt":
            drives_ids.clear()
            drives_names.clear()
            index_urls.clear()
            if Config.GDRIVE_ID:
                drives_names.append("Main")
                drives_ids.append(Config.GDRIVE_ID)
                index_urls.append(Config.INDEX_URL)
        await update_buttons(message, "private")


async def sync_jdownloader():
    if jd_listener_lock.locked():
        return
    async with jd_listener_lock:
        if await jdownloader.device.linkgrabber.is_collecting():
            return
        await jdownloader.device.linkgrabber.clear_list()
        if await jdownloader.device.downloads.query_links():
            await jdownloader.device.downloads.remove_links(
                package_ids=await jdownloader.device.downloads.query_packages()
            )
        await jdownloader.device.stop()
        await jdownloader.device.start()


@new_task
async def bot_settings(_, message):
    handler_dict[message.chat.id] = False
    msg, buttons = await get_buttons()
    await send_message(message, msg, buttons)


handler_dict = {}
