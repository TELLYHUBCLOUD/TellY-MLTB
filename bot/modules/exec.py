import asyncio
from os import path as ospath

from aiofiles import open as aiopen

from bot import LOGGER
from bot.core.telegram_manager import TgClient
from bot.helper.ext_utils.bot_utils import new_task, sync_to_async
from bot.helper.telegram_helper.message_utils import send_file, send_message


@new_task
async def execute(_, message):
    try:
        cmd = message.text.split(maxsplit=1)[1]
    except IndexError:
        return await send_message(message, "No command found!")

    reply_to_id = message.id
    if message.reply_to_message:
        reply_to_id = message.reply_to_message_id

    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    e = stderr.decode()
    o = stdout.decode()

    if not e and not o:
        o = "Finished!"
    elif not o:
        o = e
    elif e:
        o += f"\n\nError:\n{e}"

    if len(o) > 4096:
        with open("exec_output.txt", "w") as f:
            f.write(o)
        await send_file(
            message,
            "exec_output.txt",
            reply_to_id=reply_to_id,
            caption=f"<b>Exec Command:</b> <code>{cmd}</code>",
        )
        return
    await send_message(message, f"<pre language='bash'>{o}</pre>")


@new_task
async def clear_log(_, message):
    if await sync_to_async(ospath.exists, "log.txt"):
        async with aiopen("log.txt", "w") as f:
            await f.write("")
    await send_message(message, "Log Cleared!")
