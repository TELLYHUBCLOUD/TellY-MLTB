import asyncio
from asyncio import sleep
from functools import partial
from threading import Lock

from feedparser import parse as feed_parse
from httpx import AsyncClient
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler

from bot import (
    LOGGER,
    bot_loop,
    job_queue,
    rss_dict,
    scheduler,
)
from bot.core.config_manager import Config
from bot.core.telegram_manager import TgClient
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.ext_utils.db_handler import database
from bot.helper.ext_utils.exceptions import RssShutdownException
from bot.helper.ext_utils.help_messages import RSS_HELP_MESSAGE
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import (
    edit_message,
    send_message,
    send_rss,
)
from bot.modules.mirror_leech import MirrorLeech

rss_dict_lock = Lock()
handler_dict = {}


async def rss_sub(_, message, pre_event):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    if username := message.from_user.username:
        tag = f"@{username}"
    else:
        tag = message.from_user.mention

    msg = ""
    items = message.text.split("\n")
    for item in items:
        args = item.split()
        if len(args) < 2:
            await send_message(
                message,
                f"{item}. Wrong Input format. Read help message before adding new subscription!",
            )
            continue
        title = args[0].strip()
        feed_link = args[1].strip()
        if feed_link.startswith(("-inf", "-exf", "-c")):
            await send_message(
                message,
                f"Wrong Input format. Read help message before adding new subscription! Link: {feed_link}",
            )
            continue

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
        }

        inf = ""
        exf = ""
        cmd = ""
        stv = False

        if len(args) > 2:
            arg_dict = {
                "-inf": "",
                "-exf": "",
                "-c": "",
                "-stv": "false",
            }
            # Simplified args parsing for RSS
            # ...

        try:
            async with AsyncClient(
                headers=headers, follow_redirects=True, timeout=60, verify=False
            ) as client:
                res = await client.get(feed_link)
            html = res.text
            rss_d = feed_parse(html)
            last_title = rss_d.entries[0]["title"]
            last_link = rss_d.entries[0]["link"]
            async with rss_dict_lock:
                if user_id not in rss_dict:
                    rss_dict[user_id] = {}
                rss_dict[user_id][title] = {
                    "link": feed_link,
                    "last_feed": last_link,
                    "last_title": last_title,
                    "headers": headers,
                    "paused": False,
                    "filters": {
                        "inf": inf,
                        "exf": exf,
                        "command": cmd,
                        "sensitive": stv,
                        "tag": tag,
                    }
                }
            LOGGER.info(
                f"Rss Feed Added: id: {user_id} - title: {title} - link: {feed_link} - c: {cmd} - inf: {inf} - exf: {exf} - stv: {stv}"
            )
        except (IndexError, AttributeError) as e:
            emsg = f"The link: {feed_link} doesn't seem to be a RSS feed or it's region-blocked!"
            await send_message(message, emsg + f"\nError: {e}")
        except Exception as e:
            await send_message(message, f"Error: {e}")

    if not scheduler.running:
        add_job()
        scheduler.start()

    await database.rss_update(user_id)
    await update_rss_menu(pre_event)


async def rss_list(query, start, all_users=False):
    user_id = query.from_user.id
    buttons = ButtonMaker()
    if all_users:
        list_feed = f"<b>All RSS Subscriptions:</b>\n\n"
    else:
        list_feed = f"<b>Your RSS Subscriptions:</b>\n\n"

    async with rss_dict_lock:
        if user_id in rss_dict:
            keysCount = len(rss_dict[user_id])
            for index, (title, data) in enumerate(
                list(rss_dict[user_id].items())[start : 5 + start]
            ):
                list_feed += f"\n\n<b>Title:</b> <code>{title}</code>\n"
                list_feed += f"<b>Feed Url:</b> <code>{data['link']}</code>\n"
                list_feed += f"<b>Paused:</b> <code>{data['paused']}</code>\n"
                list_feed += f"<b>Command:</b> <code>{data['filters']['command']}</code>\n"

    if keysCount > 5:
        for x in range(0, keysCount, 5):
            buttons.data_button(
                f"{int(x / 5)}", f"rss list {user_id} {x}", position="footer"
            )
    button = buttons.build_menu(2)
    if query.message.text.html == list_feed:
        return
    await edit_message(query.message, list_feed, button)


async def rss_get(_, message, pre_event):
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 2:
        await send_message(
            message,
            f"{args}. Wrong Input format. You should add number of the items you want to get. Read help message before adding new subscription!",
        )
        await update_rss_menu(pre_event)
        return

    try:
        count = int(args[1])
        title = args[0]
    except ValueError:
        await send_message(message, "Count must be an integer!")
        return

    async with rss_dict_lock:
        data = rss_dict.get(user_id, {}).get(title)
        if data and count > 0:
            try:
                msg = await send_message(
                    message, f"Getting the last <b>{count}</b> item(s) from {title}"
                )
                headers = data.get("headers", {})
                async with AsyncClient(
                    headers=headers, follow_redirects=True, timeout=60, verify=False
                ) as client:
                    res = await client.get(data["link"])
                html = res.text
                rss_d = feed_parse(html)
                item_count = 0
                while item_count < count:
                    try:
                        item = rss_d.entries[item_count]
                        # Process item similar to monitor logic...
                        # Placeholder logic
                        item_count += 1
                    except IndexError:
                        break
            except Exception as e:
                LOGGER.error(str(e))
                await edit_message(
                    msg, f"Error getting items: {e}"
                )
        else:
            await send_message(message, "Feed not found or count is invalid!")

    await update_rss_menu(pre_event)


async def update_rss_menu(query):
    # Implementation to update RSS menu
    pass


async def event_handler(client, query, pfunc):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = time()

    async def event_filter(_, __, event):
        user = event.from_user or event.sender_chat
        return bool(
            user.id == user_id
            and event.chat.id == query.message.chat.id
            and event.text
        )

    handler = client.add_handler(
        MessageHandler(pfunc, create(event_filter)), group=-1
    )
    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
    client.remove_handler(*handler)


@new_task
async def rss_listener(client, query):
    user_id = query.from_user.id
    data = query.data.split()
    if int(data[2]) != user_id and not await CustomFilters.sudo("", query):
        await query.answer(
            text="You don't have permission to use these buttons!", show_alert=True
        )
    elif data[1] == "close":
        await query.answer()
        await delete_message(query.message.reply_to_message)
        await delete_message(query.message)
    elif data[1] == "back":
        await query.answer()
        await update_rss_menu(query)
    elif data[1] == "sub":
        await query.answer()
        handler_dict[user_id] = True
        pfunc = partial(rss_sub, pre_event=query)
        await event_handler(client, query, pfunc)
    elif data[1] == "list":
        await query.answer()
        start = int(data[3])
        await rss_list(query, start)
    elif data[1] == "get":
        await query.answer()
        handler_dict[user_id] = True
        pfunc = partial(rss_get, pre_event=query)
        await event_handler(client, query, pfunc)
    elif data[1] == "unsubscribe":
        await query.answer()
        # Logic to unsubscribe
    elif data[1] == "pause":
        await query.answer()
        async with rss_dict_lock:
            for info in rss_dict[int(data[2])].values():
                info["paused"] = True
        await database.rss_update(int(data[2]))
    elif data[1] == "resume":
        await query.answer()
        async with rss_dict_lock:
            for info in rss_dict[int(data[2])].values():
                info["paused"] = False
        if scheduler.state == 2:
            scheduler.resume()
        await database.rss_update(int(data[2]))


async def rss_monitor():
    if not Config.RSS_CHAT:
        LOGGER.warning("RSS_CHAT not set! RSS Monitor will not work.")
        return
    if len(rss_dict) == 0:
        return
    # Monitor logic here...
    # Placeholder for brevity
    LOGGER.info("RSS Monitor Cycle")


def add_job():
    scheduler.add_job(
        rss_monitor,
        "interval",
        seconds=Config.RSS_DELAY,
        id="rss",
        name="RSS",
        replace_existing=True,
    )
