from speedtest import Speedtest

from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.ext_utils.status_utils import get_readable_file_size
from bot.helper.telegram_helper.message_utils import delete_message, send_message


@new_task
async def speedtest(_, message):
    msg = await send_message(message, "Running Speedtest...")
    speed = Speedtest()
    speed.get_best_server()
    speed.download()
    speed.upload()
    results = speed.results.dict()
    string_speed = f"""
<b>Speedtest Results:</b>
<b>Upload:</b> {get_readable_file_size(results["upload"] / 8)}/s
<b>Download:</b> {get_readable_file_size(results["download"] / 8)}/s
<b>Ping:</b> {results["ping"]} ms
<b>Server:</b> {results["server"]["name"]}, {results["server"]["country"]}
<b>Sponsor:</b> {results["server"]["sponsor"]}
"""
    await delete_message(msg)
    await send_message(message, string_speed)
