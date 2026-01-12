import re
from os import path as ospath
from os import walk

from aiofiles.os import makedirs, remove

from bot import LOGGER, bot_loop, task_dict, task_dict_lock

MERGE_SESSIONS = {}
from bot.helper.aeon_utils.access_check import error_check
from bot.helper.ext_utils.bot_utils import (
    arg_parser,
    sync_to_async,
)
from bot.helper.ext_utils.links_utils import is_telegram_link, is_url
from bot.helper.ext_utils.media_utils import FFMpeg, get_codec_info, get_media_info
from bot.helper.listeners.task_listener import TaskListener
from bot.helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from bot.helper.mirror_leech_utils.status_utils.ffmpeg_status import FFmpegStatus
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.message_utils import (
    auto_delete_message,
    delete_links,
    send_message,
    send_status_message,
)


class Merge(TaskListener):
    def __init__(self, client, message, **kwargs):
        self.message = message
        self.client = client
        super().__init__()
        self.is_leech = True
        self.is_merge = True
        self.bulk = []
        self.multi = 0
        self.options = ""
        self.same_dir = {}
        self.multi_tag = ""
        self.inputs = []
        self.total_batch_files = 0
        self.current_batch_files = 0
        self.output_name = ""
        self.name_subfix = ""

    async def new_event(self):
        text = self.message.text.split("\n")
        input_list = text[0].split(" ")
        error_msg, error_button = await error_check(self.message)
        if error_msg:
            await delete_links(self.message)
            error = await send_message(self.message, error_msg, error_button)
            return await auto_delete_message(error, time=300)

        args = {
            "link": "",
            "-i": 0,
            "-n": "",
            "-up": "",
            "-rcf": "",
            "-b": False,
        }

        arg_parser(input_list[1:], args)

        await self.get_tag(text)

        self.link = args["link"]
        self.name = ""
        self.output_name = args["-n"]
        self.up_dest = args["-up"]
        self.rc_flags = args["-rcf"]
        self.multi = args["-i"]
        is_bulk = args["-b"]
        bulk_start = 0
        bulk_end = 0

        if not isinstance(is_bulk, bool):
            dargs = is_bulk.split(":")
            bulk_start = int(dargs[0]) if dargs[0] else 0
            if len(dargs) == 2:
                bulk_end = int(dargs[1]) if dargs[1] else 0
            is_bulk = True

        if not is_bulk:
            from bot.helper.ext_utils.bulk_links import extract_bulk_links

            self.bulk = await extract_bulk_links(self.message, bulk_start, bulk_end)
            if len(self.bulk) > 1:
                is_bulk = True

        if is_bulk:
            await self.init_bulk(input_list, bulk_start, bulk_end, Merge)
            return None

        # Parse Inputs from text (Multiple links / Ranges)
        for line in text:
            line = line.strip()
            if not line:
                continue
            # Check for TG Range: link/11-20
            if is_telegram_link(line):
                match = re.search(
                    r"(https?://t\.me/(?:c/)?(?:[\w\d]+)/)(\d+)-(\d+)", line
                )
                if match:
                    base = match.group(1)
                    start = int(match.group(2))
                    end = int(match.group(3))
                    if start <= end:
                        for i in range(start, end + 1):
                            self.inputs.append(f"{base}{i}")
                    continue
            # Normal Link
            if is_url(line) or hasattr(
                line, "download"
            ):  # Handle reply object later
                self.inputs.append(line)

        # If reply object and no text links
        if not self.inputs and (reply_to := self.message.reply_to_message):
            if reply_to.document or reply_to.video or reply_to.audio:
                self.inputs.append(reply_to)

        if not self.inputs and self.link:
            if is_telegram_link(self.link):
                match = re.search(
                    r"(https?://t\.me/(?:c/)?(?:[\w\d]+)/)(\d+)-(\d+)", self.link
                )
                if match:
                    base = match.group(1)
                    start = int(match.group(2))
                    end = int(match.group(3))
                    if start <= end:
                        for i in range(start, end + 1):
                            self.inputs.append(f"{base}{i}")
                else:
                    self.inputs.append(self.link)
            else:
                self.inputs.append(self.link)

        # Remove duplicates while preserving order
        seen = set()
        unique_inputs = []
        for inp in self.inputs:
            inp_str = str(inp)
            if inp_str not in seen:
                seen.add(inp_str)
                unique_inputs.append(inp)
        self.inputs = unique_inputs

        if not self.inputs:
            # Check for Session Start (Blank Command)
            user_id = self.message.from_user.id
            if user_id not in MERGE_SESSIONS:
                MERGE_SESSIONS[user_id] = {
                    "inputs": [],
                    "message": self.message,
                    "client": self.client,
                    "adapter": self,
                }
                await send_message(
                    self.message,
                    f"Merge Session Started!\nSend/Forward files to add them (Max 10).\nUse /{BotCommands.MdoneCommand[0]} to start merging.",
                )
            else:
                count = len(MERGE_SESSIONS[user_id]["inputs"])
                await send_message(
                    self.message,
                    f"Merge Session Active.\nFiles Added: {count}/10\nSend files to add, or /{BotCommands.MdoneCommand[0]} to start.",
                )
            return None

        if len(self.inputs) > 10:
            await send_message(
                self.message,
                "Merge Limit: You can only merge up to 10 files/links at once.",
            )
            return None

        self.total_batch_files = len(self.inputs)
        LOGGER.info(f"Merge Request: {self.total_batch_files} inputs")

        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, e)
            return None

        if len(self.inputs) == 1 and not is_bulk:
            user_id = self.message.from_user.id
            session = MERGE_SESSIONS.get(user_id)

            if not session:
                MERGE_SESSIONS[user_id] = {
                    "inputs": [],
                    "message": self.message,
                    "client": self.client,
                    "adapter": self,  # store ref to adapter/listener for context if needed
                }
                session = MERGE_SESSIONS[user_id]

            # Check if link already exists in session to prevent dupes (optional, but good)
            # User requested: "1 TASK ADDED MAX 9 FILE" - imply up to 10 total
            if len(session["inputs"]) >= 10:
                await send_message(
                    self.message,
                    f"Merge Limit Reached! Use /{BotCommands.MdoneCommand[0]} to start.",
                )
                return None

            link = self.inputs[0]
            session["inputs"].append(link)
            count = len(session["inputs"])

            if count == 10:
                # Auto start
                self.inputs = session["inputs"]
                del MERGE_SESSIONS[user_id]
                await send_message(
                    self.message, "Limit reached (10/10). Starting Merge..."
                )
                await self._proceed_to_download()
            else:
                await send_message(
                    self.message,
                    f"File Added: {count}/10\nReply to next file or use /{BotCommands.MdoneCommand[0]} to start.",
                )
            return None

        # Explicit bulk or >1 inputs -> Immediate Start (Classic Mode)
        await self._proceed_to_download()
        return None

    async def get_tg_link_message(self, link):
        message = None
        if is_telegram_link(link):
            try:
                # Regex to handle all standard Telegram link formats, ignoring query params
                # Matches: t.me/(c/)?(CHAT_ID_OR_USER)/(MSG_ID)
                pattern = r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:c/)?([\w\d]+)/(\d+)"
                match = re.search(pattern, link)

                if match:
                    chat_identifier = match.group(1)
                    msg_id = int(match.group(2))

                    if "c/" in link:
                        # Private chat ID (make it -100 prefixed)
                        chat_id = int("-100" + chat_identifier)
                    else:
                        # Username or ID
                        chat_id = chat_identifier
                        # Try converting to int if it's purely numeric (rare but possible for some IDs)
                        if str(chat_id).isdigit():
                            chat_id = int(chat_id)

                    message = await self.client.get_messages(chat_id, msg_id)
                else:
                    LOGGER.error(f"Malformed TG Link: {link}")
            except Exception as e:
                LOGGER.error(f"Error getting TG Link: {e}")
        return message

    async def _proceed_to_download(self):
        from bot.helper.mirror_leech_utils.download_utils.telegram_download import (
            TelegramDownloadHelper,
        )

        path = f"{self.dir}/"
        self.current_file_index = 0

        for index, link in enumerate(self.inputs):
            self.current_file_index = index + 1
            # Check cancel
            if self.is_cancelled:
                return

            self.link = link
            # Use unique subdir for each file to avoid collisions
            current_path = f"{path}{index}/"
            await makedirs(current_path, exist_ok=True)

            if hasattr(link, "download") or (
                isinstance(link, (str, bytes))
                and hasattr(self.message, "reply_to_message")
                and link == self.message.reply_to_message
            ):
                # Handle cases where link is already a message object or needs to be downloaded as such
                # Simplified: if it's not a URL/TG link string, treat as message if possible
                pass

            if not isinstance(link, (str, bytes)):
                # Message object
                await TelegramDownloadHelper(self).add_download(
                    link,
                    current_path,
                    self.client,
                )
            elif is_telegram_link(str(link)):
                message = await self.get_tg_link_message(link)
                if message:
                    if message.document or message.video or message.audio:
                        await TelegramDownloadHelper(self).add_download(
                            message,
                            current_path,
                            self.client,
                        )
                    else:
                        self.total_batch_files -= 1
                else:
                    LOGGER.error(f"Failed to get message for: {link}")
                    self.total_batch_files -= 1  # adjust total
            elif is_url(str(link)):
                await add_aria2_download(self, current_path, [], None, None)
            else:
                self.total_batch_files -= 1

        if self.total_batch_files == 0:
            await send_message(self.message, "No valid inputs found.")
            return

    async def on_download_complete(self):
        self.current_batch_files += 1
        if self.current_batch_files < self.total_batch_files:
            return

        input_files = []
        for root, _, filess in await sync_to_async(walk, self.dir):
            for file in filess:
                input_files.append(ospath.join(root, file))

        if not input_files or len(input_files) < 2:
            await self.on_upload_error(
                f"Need at least 2 files to merge. Found: {len(input_files)}"
            )
            return

        input_files.sort()

        # Create input.txt
        input_txt_path = f"{self.dir}/input.txt"
        with open(input_txt_path, "w") as f:
            for file in input_files:
                f.write(f"file '{file}'\n")

        # Prepare FFMpeg Status
        ffmpeg = FFMpeg(self)
        async with task_dict_lock:
            if self.mid in task_dict:
                self.gid = task_dict[self.mid].gid()
            task_dict[self.mid] = FFmpegStatus(self, ffmpeg, self.gid, "merging")

        await send_status_message(self.message)

        # Smart Renaming Logic
        if not self.output_name:
            try:
                # Try to detect series pattern from input files
                input_filenames = [ospath.basename(f) for f in input_files]
                # Regex for S01E01 or Episode 01
                pattern_se = re.compile(r"(.*?)S(\d+)\s*E(\d+)", re.IGNORECASE)
                pattern_ep = re.compile(r"(.*?)Episode\s*(\d+)", re.IGNORECASE)

                series_name = ""
                season = ""
                episodes = []

                for fname in input_filenames:
                    if match := pattern_se.search(fname):
                        series_name = match.group(1).replace(".", " ").strip()
                        season = match.group(2)
                        episodes.append(int(match.group(3)))
                    elif match := pattern_ep.search(fname):
                        series_name = match.group(1).replace(".", " ").strip()
                        season = "01"  # Default to S01 for "Episode X"
                        episodes.append(int(match.group(2)))

                if series_name and episodes:
                    episodes.sort()
                    start_ep = episodes[0]
                    end_ep = episodes[-1]
                    self.output_name = (
                        f"{series_name} S{season}E{start_ep:02d}-E{end_ep:02d}.mp4"
                    )
                    LOGGER.info(f"Smart Renaming: {self.output_name}")
                else:
                    self.output_name = ospath.basename(input_files[0])

            except Exception as e:
                LOGGER.error(f"Smart renaming failed: {e}")
                self.output_name = ospath.basename(input_files[0])

        # Apply output name
        if self.name_subfix:
            name, ext = ospath.splitext(self.output_name)
            self.output_name = f"{name} {self.name_subfix}{ext}"

        self.name = self.output_name

        has_ass = False
        for file in input_files:
            codecs = await get_codec_info(file)
            if "ass" in codecs:
                has_ass = True
                break

        if has_ass:
            if not self.name.lower().endswith(".mkv"):
                base_name = ospath.splitext(self.name)[0]
                self.name = f"{base_name}.mkv"
        elif not self.name.lower().endswith(
            ".mp4"
        ) and not self.name.lower().endswith(".mkv"):
            self.name += ".mp4"

        output_file = f"{self.dir}/{self.name}"

        cmd = [
            "xtra",
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            input_txt_path,
            "-map",
            "0",
            "-c",
            "copy",
            "-metadata",
            f"title={self.name}",
            output_file,
        ]
        LOGGER.info(f"Running Merge CMD: {cmd}")

        total_duration = 0
        for file in input_files:
            duration = (await get_media_info(file))[0]
            total_duration += duration

        res = await ffmpeg.metadata_watermark_cmds(cmd, output_file, total_duration)

        if res:
            # Cleanup inputs
            for file in input_files:
                await remove(file)
            await remove(input_txt_path)
            await super().on_download_complete()
        else:
            await self.on_upload_error("Merge Failed. Check logs.")


async def merge(client, message):
    from bot.helper.ext_utils.bulk_links import extract_bulk_links

    bulk = await extract_bulk_links(message, "0", "0")
    if len(bulk) > 1:
        await Merge(client, message).init_bulk(
            message.text.split("\n")[0].split(), 0, 0, Merge
        )
    else:
        bot_loop.create_task(Merge(client, message).new_event())


async def merge_done(client, message):
    user_id = message.from_user.id
    if user_id not in MERGE_SESSIONS:
        await send_message(
            message,
            f"No active merge session! Use /{BotCommands.MergeCommand[0]} to start one.",
        )
        return

    session = MERGE_SESSIONS[user_id]
    if len(session["inputs"]) < 2:
        await send_message(message, "Need at least 2 files to merge!")
        return

    # Trigger Merge
    session["message"]  # Original first message for auth checks etc

    listener = Merge(client, message)  # Use current message for listener context
    listener.inputs = session["inputs"]
    listener.total_batch_files = len(listener.inputs)
    del MERGE_SESSIONS[user_id]

    # Parse arguments from /mdone command
    text = message.text.split(maxsplit=1)
    if len(text) > 1:
        args = {"-n": ""}
        input_args = text[1].split()
        if "-n" in input_args:
            arg_parser(input_args, args)
            if args["-n"]:
                listener.output_name = args["-n"]
        else:
            # Treat raw text as suffix
            listener.name_subfix = text[1].strip()

    await send_message(
        message, f"Merge Started with {listener.total_batch_files} files..."
    )

    try:
        await listener.before_start()
        await listener._proceed_to_download()
        await send_status_message(message)
    except Exception as e:
        await send_message(message, str(e))


async def merge_session_handler(client, message):
    user_id = message.from_user.id
    if user_id not in MERGE_SESSIONS:
        return

    # Check if message has media
    media = message.document or message.video or message.audio
    if not media:
        return

    session = MERGE_SESSIONS[user_id]

    if len(session["inputs"]) >= 10:
        await send_message(
            message,
            f"Merge Limit Reached (10/10)!\nUse /{BotCommands.MdoneCommand[0]} to start.",
        )
        return

    # Add query message to session inputs
    session["inputs"].append(message)
    count = len(session["inputs"])

    if count == 10:
        # Auto start
        listener = Merge(client, session["message"])
        listener.inputs = session["inputs"]
        listener.total_batch_files = 10
        del MERGE_SESSIONS[user_id]

        await send_message(message, "Limit reached (10/10). Starting Merge...")
        try:
            await listener.before_start()
            await listener._proceed_to_download()
        except Exception as e:
            await send_message(message, str(e))
    else:
        await send_message(
            message,
            f"Added: {count}/10\nSend more or /{BotCommands.MdoneCommand[0]}",
        )
