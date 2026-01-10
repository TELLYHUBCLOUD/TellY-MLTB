from asyncio import sleep

from bot import multi_tags, task_dict, task_dict_lock
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.message_utils import (
    send_message,
)


@new_task
async def cancel_task(_, message):
    user_id = message.from_user.id if message.from_user else message.sender_chat.id
    msg = message.text.split()
    if len(msg) > 1:
        gid = msg[1]
        if len(gid) == 4:
            multi_tags.discard(gid)
            return
        task = await get_task_by_gid(gid)
        if task is None:
            await send_message(message, f"GID: {gid} Not Found.")
            return
    elif reply_to_id := message.reply_to_message_id:
        async with task_dict_lock:
            task = task_dict.get(reply_to_id)
        if task is None:
            await send_message(message, "This is not an active task!")
            return
    elif len(msg) == 1:
        msg = f"Reply to an active Command message which was used to start the download or send <code>/{BotCommands.CancelTaskCommand} GID</code> to cancel it!"
        await send_message(message, msg)
        return
    if user_id != task.listener.user_id and not await CustomFilters.sudo(
        "", message
    ):
        await send_message(message, "This task is not for you!")
        return
    obj = task.task()
    await obj.cancel_task()


@new_task
async def cancel_multi(_, message):
    user_id = message.from_user.id if message.from_user else message.sender_chat.id
    msg = message.text.split()
    if len(msg) > 1:
        gid = msg[1]
        if len(gid) == 4:
            multi_tags.discard(gid)
            return
        task = await get_task_by_gid(gid)
        if task is None:
            await send_message(message, f"GID: {gid} Not Found.")
            return
    elif reply_to_id := message.reply_to_message_id:
        async with task_dict_lock:
            task = task_dict.get(reply_to_id)
        if task is None:
            await send_message(message, "This is not an active task!")
            return
    elif len(msg) == 1:
        msg = f"Reply to an active Command message which was used to start the download or send <code>/{BotCommands.CancelMultiCommand} GID</code> to cancel it!"
        await send_message(message, msg)
        return
    if user_id != task.listener.user_id and not await CustomFilters.sudo(
        "", message
    ):
        await send_message(message, "This task is not for you!")
        return
    obj = task.task()
    await obj.cancel_task()


@new_task
async def cancel_all(client, message):
    async with task_dict_lock:
        count = 0
        if task_dict:
            for task in list(task_dict.values()):
                obj = task.task()
                if (
                    message.from_user.id == obj.listener.user_id
                    or await CustomFilters.sudo("", message)
                ):
                    await obj.cancel_task()
                    count += 1
                    await sleep(2)
        if count > 0:
            await send_message(message, f"Cancelled {count} tasks!")
        else:
            await send_message(message, "No active tasks!")


async def get_task_by_gid(gid):
    async with task_dict_lock:
        for task in task_dict.values():
            if task.gid() == gid:
                return task
        return None
