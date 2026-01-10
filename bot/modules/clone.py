from random import SystemRandom
from string import ascii_letters, digits

from bot.helper.ext_utils.bot_utils import (
    arg_parser,
    new_task,
)
from bot.helper.ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
)
from bot.helper.listeners.task_listener import TaskListener
from bot.helper.mirror_leech_utils.gdrive_utils.clone import GoogleDriveClone
from bot.helper.mirror_leech_utils.status_utils.gdrive_status import (
    GoogleDriveStatus,
)
from bot.helper.telegram_helper.message_utils import (
    send_message,
    send_status_message,
)


class Clone(TaskListener):
    def __init__(
        self,
        client,
        message,
        _=None,
        __=None,
        ___=None,
        ____=None,
        _____=None,
        bulk=None,
        multi_tag=None,
        options="",
    ):
        if bulk is None:
            bulk = []
        self.message = message
        self.client = client
        self.multi_tag = multi_tag
        self.options = options
        self.same_dir = {}
        self.bulk = bulk
        super().__init__()
        self.is_clone = True

    @new_task
    async def new_event(self):
        text = self.message.text.split("\n")
        input_list = text[0].split(" ")

        args = {
            "link": "",
            "-i": 0,
            "-b": False,
            "-n": "",
            "-up": "",
            "-rcf": "",
            "-t": "",
        }

        arg_parser(input_list[1:], args)

        try:
            self.multi = int(args["-i"])
        except ValueError:
            self.multi = 0

        self.up_dest = args["-up"]
        self.rc_flags = args["-rcf"]
        self.link = args["link"]
        self.name = args["-n"]
        self.thumb = args["-t"]

        is_bulk = args["-b"]
        bulk_start = 0
        bulk_end = 0

        if not isinstance(is_bulk, bool):
            dargs = is_bulk.split(":")
            bulk_start = dargs[0] or "0"
            if len(dargs) == 2:
                bulk_end = dargs[1] or "0"
            is_bulk = True

        if is_bulk:
            await self.init_bulk(input_list, bulk_start, bulk_end, Clone)
            return

        await self.get_tag(text)

        if not self.link and (reply_to := self.message.reply_to_message):
            self.link = reply_to.text.split("\n", 1)[0].strip()

        await self.run_multi(input_list, Clone)

        if not self.link:
            return

        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, e)
            return

        msg, button = await stop_duplicate_check(self)
        if msg:
            await send_message(self.message, msg, button)
            return

        check, _, _, _ = await check_running_tasks(self)
        if check:
            return

        await self.on_download_start()

        if self.multi <= 1:
            await send_status_message(self.message)

        if self.up_dest == "rcl":
            # Rclone Clone Logic Here
            pass
        else:
            drive = GoogleDriveClone(self)
            if self.multi > 1:
                self.mid = "".join(
                    SystemRandom().choices(ascii_letters + digits, k=10)
                )
            async with task_dict_lock:
                task_dict[self.mid] = GoogleDriveStatus(self, drive, self.mid, "cl")
            await drive.clone()
