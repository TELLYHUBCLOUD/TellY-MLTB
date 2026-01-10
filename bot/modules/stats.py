from time import time

from psutil import (
    cpu_percent,
    disk_usage,
    net_io_counters,
    swap_memory,
    virtual_memory,
)

from bot import bot_start_time
from bot.helper.ext_utils.bot_utils import (
    get_readable_file_size,
    get_readable_time,
    new_task,
)
from bot.helper.telegram_helper.message_utils import send_message


@new_task
async def stats(_, message):
    total, used, free, disk = disk_usage("/")
    swap = swap_memory()
    memory = virtual_memory()
    per_cpu = cpu_percent(interval=1, percpu=True)
    per_cpu_str = " | ".join(
        [f"CPU{i + 1}: {round(p)}%" for i, p in enumerate(per_cpu)]
    )
    stats = f"""
<b>Bot Uptime:</b> {get_readable_time(time() - bot_start_time)}

<b>Total Disk Space:</b> {get_readable_file_size(total)}
<b>Used:</b> {get_readable_file_size(used)}
<b>Free:</b> {get_readable_file_size(free)}

<b>Upload:</b> {get_readable_file_size(net_io_counters().bytes_sent)}
<b>Download:</b> {get_readable_file_size(net_io_counters().bytes_recv)}

<b>CPU:</b> {cpu_percent(interval=1)}%
<b>CPU Cores:</b> {per_cpu_str}
<b>RAM:</b> {memory.percent}%
<b>DISK:</b> {disk}%

<b>SWAP:</b> {get_readable_file_size(swap.total)}
<b>Used:</b> {get_readable_file_size(swap.used)}
<b>Free:</b> {get_readable_file_size(swap.free)}
"""
    await send_message(message, stats)
