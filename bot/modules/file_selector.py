from asyncio import iscoroutinefunction

from bot import task_dict, task_dict_lock
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.ext_utils.status_utils import MirrorStatus
from bot.helper.telegram_helper.message_utils import send_message


@new_task
async def select(_, message):
    if not message.reply_to_message:
        await send_message(message, "Reply to an active task message!")
        return
    reply_to_id = message.reply_to_message.id
    async with task_dict_lock:
        task = task_dict.get(reply_to_id)
    if not task:
        await send_message(message, "Active task not found!")
        return
    if (
        message.from_user.id != task.listener.user_id
        and not await CustomFilters.sudo("", message)
    ):
        await send_message(message, "This task is not for you!")
        return
    if not iscoroutinefunction(task.status):
        await send_message(message, "The task have finished the download stage!")
        return
    if await task.status() not in [
        MirrorStatus.STATUS_DOWNLOAD,
        MirrorStatus.STATUS_PAUSED,
        MirrorStatus.STATUS_QUEUEDL,
    ]:
        await send_message(
            message,
            f"Task state: {await task.status()} is not allowed for selection!",
        )
        return
    if not task.listener.select:
        await send_message(message, "Selection wasn't enabled for this task!")
        return

    # Implement selection logic here (if needed to call specific task method)
    # Most downloaders handle selection internally or via button callbacks
    await send_message(message, "Selection triggered (Implementation dependent).")
