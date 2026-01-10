from argparse import ArgumentParser
from asyncio import create_subprocess_exec, create_subprocess_shell
from asyncio.subprocess import PIPE
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from time import time

from bot import (
    DOWNLOAD_DIR,
    LOGGER,
    bot_loop,
    bot_start_time,
    cpu_eater_lock,
    intervals,
    task_dict,
    task_dict_lock,
)
from bot.core.config_manager import Config
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker

COMMAND_USAGE = {}


class SetInterval:
    def __init__(self, interval, action, *args, **kwargs):
        self.interval = interval
        self.action = action
        self.task = bot_loop.create_task(self._set_interval(*args, **kwargs))

    async def _set_interval(self, *args, **kwargs):
        while True:
            await self.action(*args, **kwargs)
            await sleep(self.interval)

    def cancel(self):
        self.task.cancel()


def cmd_exec(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        async with cpu_eater_lock:
            return await func(self, *args, **kwargs)

    return wrapper


def sync_to_async(func, *args, wait=True, **kwargs):
    pfunc = partial(func, *args, **kwargs)
    future = bot_loop.run_in_executor(None, pfunc)
    return future if wait else bot_loop.create_task(future)


async def execute_command(command: str, *args):
    """Executes a shell command asynchronously."""
    process = await create_subprocess_exec(
        command,
        *args,
        stdout=PIPE,
        stderr=PIPE,
    )
    stdout, stderr = await process.communicate()
    return stdout.decode().strip(), stderr.decode().strip(), process.returncode


async def create_help_buttons():
    buttons = ButtonMaker()
    buttons.data_button("Mirror", "help mirror")
    buttons.data_button("Youtube", "help yt")
    buttons.data_button("Clone", "help clone")
    buttons.data_button("Close", "help close")
    return buttons.build_menu(2)


async def get_readable_time(seconds):
    result = ""
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f"{days}d "
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f"{hours}h "
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f"{minutes}m "
    seconds = int(seconds)
    result += f"{seconds}s"
    return result


async def get_readable_file_size(size_in_bytes):
    if size_in_bytes is None:
        return "0B"
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f"{round(size_in_bytes, 2)}{['B', 'KB', 'MB', 'GB', 'TB', 'PB'][index]}"
    except IndexError:
        return "File too large"


async def get_progress_bar_string(status):
    completed = status.processed_bytes()
    total = status.size()
    p = 0 if total == "0B" else round(status.processed_raw() / status.size_raw() * 100)
    p = min(p, 100)
    return f"[{'■' * (p // 10)}{'□' * (10 - p // 10)}] {p}%"


def new_task(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return bot_loop.create_task(func(*args, **kwargs))

    return wrapper


async def update_user_ldata(user_id, key, value):
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id][key] = value


def arg_parser(items, arg_base):
    if not items:
        return arg_base
    bool_arg_set = {
        "-b",
        "-e",
        "-z",
        "-s",
        "-j",
        "-d",
        "-sv",
        "-ss",
        "-f",
        "-fd",
        "-fu",
        "-hl",
        "-ut",
        "-bt",
        "-doc",
        "-med",
    }
    t = len(items)
    for i in range(t):
        if items[i].startswith("-"):
            if items[i] in bool_arg_set:
                arg_base[items[i]] = True
            else:
                arg_base[items[i]] = items[i + 1]
        elif i == 0 and not items[i].startswith("-"):
            arg_base["link"] = items[i]
        elif items[i - 1] in ["-n", "-up", "-rcf", "-au", "-ap", "-h", "-t", "-m"]:
            arg_base[items[i - 1]] = items[i]
        elif items[i - 1] in ["-c", "-l", "-g", "-p", "-k", "-sa", "-i", "-sp"]:
            arg_base[items[i - 1]] = items[i]
    return arg_base


def get_size_bytes(size):
    if not size:
        return 0
    size = size.lower()
    if size.endswith("kb"):
        return int(float(size[:-2]) * 1024)
    if size.endswith("mb"):
        return int(float(size[:-2]) * 1048576)
    if size.endswith("gb"):
        return int(float(size[:-2]) * 1073741824)
    if size.endswith("tb"):
        return int(float(size[:-2]) * 1099511627776)
    if size.endswith("b"):
        return int(float(size[:-1]))
    try:
        return int(float(size))
    except ValueError:
        return 0
