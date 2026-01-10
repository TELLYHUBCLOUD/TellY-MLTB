from logging import getLogger

from bot import LOGGER
from bot.helper.ext_utils.bot_utils import arg_parser, new_task
from bot.helper.listeners.task_listener import TaskListener
from bot.helper.telegram_helper.message_utils import (
    send_message,
)

LOGGER = getLogger(__name__)


class YtDlp(TaskListener):
    def __init__(
        self,
        client,
        message,
        _=None,
        is_leech=False,
        __=None,
        ___=None,
        same_dir=None,
        bulk=None,
        multi_tag=None,
        options="",
    ):
        if same_dir is None:
            same_dir = {}
        if bulk is None:
            bulk = []
        self.message = message
        self.client = client
        self.multi_tag = multi_tag
        self.options = options
        self.same_dir = same_dir
        self.bulk = bulk
        super().__init__()
        self.is_ytdlp = True
        self.is_leech = is_leech

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
            "-m": "",
            "-s": False,
            "-z": False,
            "-e": False,
            "-j": False,
            "-d": False,
            "-sv": False,
            "-ss": False,
            "-f": False,
            "-fd": False,
            "-fu": False,
            "-hl": False,
            "-ut": False,
            "-bt": False,
            "-doc": False,
            "-med": False,
            "-ca": "",
            "-cv": "",
            "-ns": "",
            "-np": "",
            "-md": "",
            "-tl": "",
            "-ff": set(),
            "-sp": 0,
            "-opt": "",
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
        self.split_size = args["-sp"]
        self.folder_name = args["-m"]
        self.select = args["-s"]
        self.seed = args["-d"]
        self.compress = args["-z"]
        self.extract = args["-e"]
        self.join = args["-j"]
        self.sample_video = args["-sv"]
        self.screen_shots = args["-ss"]
        self.convert_audio = args["-ca"]
        self.convert_video = args["-cv"]
        self.name_sub = args["-ns"]
        self.name_prefix = args["-np"]
        self.hybrid_leech = args["-hl"]
        self.thumbnail_layout = args["-tl"]
        self.as_doc = args["-doc"]
        self.as_med = args["-med"]
        self.ffmpeg_cmds = args["-ff"]
        self.force_run = args["-f"]
        self.force_download = args["-fd"]
        self.force_upload = args["-fu"]
        self.bot_trans = args["-bt"]
        self.user_trans = args["-ut"]
        self.metadata = args["-md"]
        self.yt_opt = args["-opt"]

        is_bulk = args["-b"]
        bulk_start = 0
        bulk_end = 0

        if not isinstance(is_bulk, bool):
            dargs = is_bulk.split(":")
            bulk_start = dargs[0] or "0"
            if len(dargs) == 2:
                bulk_end = dargs[1] or "0"
            is_bulk = True

        if not is_bulk and self.multi > 0:
            await self.run_multi(input_list, YtDlp)
            return

        await self.get_tag(text)

        if not self.link and (reply_to := self.message.reply_to_message):
            self.link = reply_to.text.split("\n", 1)[0].strip()

        if is_bulk:
            await self.init_bulk(input_list, bulk_start, bulk_end, YtDlp)
            return

        if not self.link:
            await send_message(
                self.message,
                f"Use /{self.message.command[0]} link to start download!",
            )
            return

        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, e)
            return

        # YtDlp Download Logic
