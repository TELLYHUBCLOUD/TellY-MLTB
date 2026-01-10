from bot import task_dict, task_dict_lock
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import send_message


@new_task
async def remove_from_queue(_, message):
    user_id = message.from_user.id if message.from_user else message.sender_chat.id
    msg = message.text.split()
    if len(msg) > 1:
        gid = msg[1]
        if len(msg) > 2:
            msg[2]
    elif reply_to_id := message.reply_to_message_id:
        async with task_dict_lock:
            task = task_dict.get(reply_to_id)
        if task is None:
            await send_message(message, "This is not an active task!")
            return
        gid = task.gid()
        if len(msg) > 1:
            msg[1]
    elif len(msg) in {1, 2}:
        msg = f"""Reply to an active Command message which was used to start the download/upload.
<code>/{BotCommands.ForceStartCommand[0]}</code> fd (to remove it from download queue) or fu (to remove it from upload queue) or nothing to start remove it from both download and upload queue.
Also send <code>/{BotCommands.ForceStartCommand[0]} GID</code> fu|fd or obly gid to force start by removing the task rom queue!
Examples:
<code>/{BotCommands.ForceStartCommand[1]}</code> GID fu (force upload)
<code>/{BotCommands.ForceStartCommand[1]}</code> GID (force download and upload)
"""
        await send_message(message, msg)
        return

    async with task_dict_lock:
        task = None
        for t in task_dict.values():
            if t.gid() == gid:
                task = t
                break
        if task is None:
            await send_message(message, f"GID: {gid} Not Found.")
            return

    if user_id != task.listener.user_id and not await CustomFilters.sudo(
        "", message
    ):
        await send_message(message, "This task is not for you!")
        return

    obj = task.task()
    from bot.helper.mirror_leech_utils.status_utils.queue_status import QueueStatus

    if not isinstance(obj, QueueStatus):
        await send_message(message, "This task is not in queue!")
        return

    # Implement removal logic
    # Usually this involves interacting with a QueueManager or setting flags
    # Assuming there's logic to force start in listener or QueueStatus
    # For now, just logging placeholder
    await send_message(
        message, f"Force Start Triggered for {gid} (Placeholder Logic)"
    )
