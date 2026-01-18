import re
from os import path as ospath
from os import walk

from aiofiles.os import listdir, makedirs, remove
from aioshutil import rmtree

from bot import LOGGER, bot_loop, task_dict, task_dict_lock

MERGE_SESSIONS = {}

from bot.helper.aeon_utils.access_check import error_check
from bot.helper.ext_utils.bot_utils import arg_parser, sync_to_async
from bot.helper.ext_utils.links_utils import is_telegram_link, is_url
from bot.helper.ext_utils.media_utils import FFMpeg, get_codec_info, get_media_info
from bot.helper.listeners.task_listener import TaskListener
from bot.helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.message_utils import (
    auto_delete_message,
    delete_links,
    send_message,
    send_status_message,
)


class Merge(TaskListener):
    """Handles merging of multiple media files into a single output."""

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
        self.current_file_index = 0
        self._download_complete_event = None

    async def new_event(self):
        """Main entry point for merge command processing."""
        text = self.message.text.split("\n")
        input_list = text[0].split(" ")

        # Error checking
        error_msg, error_button = await error_check(self.message)
        if error_msg:
            await delete_links(self.message)
            error = await send_message(self.message, error_msg, error_button)
            return await auto_delete_message(error, time=300)

        # Parse arguments
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

        # Handle bulk parsing
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

        # Parse inputs from text
        self.inputs = await self._parse_inputs(text)

        # Handle reply message if no inputs found
        if not self.inputs:
            self.inputs = await self._handle_reply_message()

        # Handle link argument if still no inputs
        if not self.inputs and self.link:
            self.inputs = await self._parse_link_argument()

        # Remove duplicates while preserving order
        self.inputs = self._remove_duplicates(self.inputs)

        # Handle empty inputs - start/check session
        if not self.inputs:
            return await self._handle_session_mode()

        # Check merge limit
        if len(self.inputs) > 20:
            await send_message(
                self.message,
                "⚠️ Merge Limit: You can only merge up to 20 files/links at once.",
            )
            return None

        self.total_batch_files = len(self.inputs)
        LOGGER.info(f"Merge Request: {self.total_batch_files} inputs")

        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, f"❌ Error: {e}")
            return None

        # Handle single input - add to session
        if len(self.inputs) == 1 and not is_bulk:
            return await self._handle_single_input()

        # Multiple inputs -> Immediate Start
        await self._proceed_to_download()
        return None

    async def _parse_inputs(self, text_lines: list) -> list:
        """Parse input links from message text."""
        inputs = []
        for line in text_lines:
            line = line.strip()
            if not line:
                continue

            # Check for TG Range: link/11-20
            if is_telegram_link(line):
                range_inputs = self._parse_telegram_range(line)
                if range_inputs:
                    inputs.extend(range_inputs)
                    continue

            # Normal Link
            if is_url(line):
                inputs.append(line)

        return inputs

    def _parse_telegram_range(self, link: str) -> list:
        """Parse Telegram link range (e.g., t.me/channel/1-20)."""
        match = re.search(r"(https?://t\.me/(?:c/)?[\w\d]+/)(\d+)-(\d+)", link)
        if match:
            base = match.group(1)
            start = int(match.group(2))
            end = int(match.group(3))
            if start <= end:
                return [f"{base}{i}" for i in range(start, end + 1)]
        return []

    async def _handle_reply_message(self) -> list:
        """Handle reply message for media extraction."""
        reply_to = self.message.reply_to_message
        if reply_to and (reply_to.document or reply_to.video or reply_to.audio):
            return [reply_to]
        return []

    async def _parse_link_argument(self) -> list:
        """Parse the link argument for inputs."""
        inputs = []
        if is_telegram_link(self.link):
            range_inputs = self._parse_telegram_range(self.link)
            if range_inputs:
                inputs.extend(range_inputs)
            else:
                inputs.append(self.link)
        else:
            inputs.append(self.link)
        return inputs

    def _remove_duplicates(self, inputs: list) -> list:
        """Remove duplicate inputs while preserving order."""
        seen = set()
        unique_inputs = []
        for inp in inputs:
            inp_str = str(inp) if not hasattr(inp, "id") else str(inp.id)
            if inp_str not in seen:
                seen.add(inp_str)
                unique_inputs.append(inp)
        return unique_inputs

    async def _handle_session_mode(self):
        """Handle merge session start/status."""
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
                f"✅ **Merge Session Started!**\n\n"
                f"📤 Send/Forward files to add them (Max 20).\n"
                f"🔄 Use /{BotCommands.MdoneCommand[0]} to start merging.",
            )
        else:
            count = len(MERGE_SESSIONS[user_id]["inputs"])
            await send_message(
                self.message,
                f"📁 **Merge Session Active**\n\n"
                f"Files Added: {count}/20\n"
                f"Send files to add, or /{BotCommands.MdoneCommand[0]} to start.",
            )

    async def _handle_single_input(self):
        """Handle single input - add to session."""
        user_id = self.message.from_user.id

        if user_id not in MERGE_SESSIONS:
            MERGE_SESSIONS[user_id] = {
                "inputs": [],
                "message": self.message,
                "client": self.client,
                "adapter": self,
            }

        session = MERGE_SESSIONS[user_id]

        if len(session["inputs"]) >= 20:
            await send_message(
                self.message,
                f"⚠️ Merge Limit Reached!\n"
                f"Use /{BotCommands.MdoneCommand[0]} to start.",
            )
            return

        link = self.inputs[0]
        session["inputs"].append(link)
        count = len(session["inputs"])

        if count == 20:
            # Auto start at limit
            self.inputs = session["inputs"]
            del MERGE_SESSIONS[user_id]
            await send_message(
                self.message, "✅ Limit reached (20/20). Starting Merge..."
            )
            await self._proceed_to_download()
        else:
            await send_message(
                self.message,
                f"✅ File Added: {count}/20\n"
                f"Reply to next file or use /{BotCommands.MdoneCommand[0]} to start.",
            )
        return

    async def get_tg_link_message(self, link: str):
        """Fetch Telegram message from link."""
        if not is_telegram_link(link):
            return None

        try:
            pattern = (
                r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:c/)?([\w\d_]+)/(\d+)"
            )
            match = re.search(pattern, link)

            if not match:
                LOGGER.error(f"Malformed TG Link: {link}")
                return None

            chat_identifier = match.group(1)
            msg_id = int(match.group(2))

            if "c/" in link:
                chat_id = int(f"-100{chat_identifier}")
            else:
                chat_id = chat_identifier
                if str(chat_id).isdigit():
                    chat_id = int(chat_id)

            return await self.client.get_messages(chat_id, msg_id)

        except Exception as e:
            LOGGER.error(f"Error getting TG Link message: {e}")
            return None

    async def _proceed_to_download(self):
        """Process all inputs and download files."""
        from bot.helper.mirror_leech_utils.download_utils.telegram_download import (
            TelegramDownloadHelper,
        )

        path = f"{self.dir}/"
        self.current_file_index = 0
        failed_downloads = 0

        for index, link in enumerate(self.inputs):
            if self.is_cancelled:
                LOGGER.info("Merge cancelled by user")
                return

            self.current_file_index = index + 1
            filename = "None"
            if hasattr(link, "document") and link.document:
                filename = link.document.file_name
            elif hasattr(link, "video") and link.video:
                filename = link.video.file_name
            elif hasattr(link, "audio") and link.audio:
                filename = link.audio.file_name
            elif isinstance(link, str):
                filename = ospath.basename(link)

            self.name = (
                f"[{self.current_file_index}/{self.total_batch_files}] {filename}"
            )

            current_path = f"{path}{index}/"
            await makedirs(current_path, exist_ok=True)

            try:
                success = await self._download_single_input(
                    link, current_path, TelegramDownloadHelper
                )
                if not success:
                    failed_downloads += 1
            except Exception as e:
                LOGGER.error(f"Download error for input {index}: {e}")
                failed_downloads += 1

        # Adjust total for failed downloads
        self.total_batch_files -= failed_downloads

        if self.total_batch_files < 2:
            await send_message(
                self.message,
                f"❌ Need at least 2 valid files to merge.\n"
                f"Valid files: {self.total_batch_files}",
            )
            return

    async def _download_single_input(
        self, link, current_path, TelegramDownloadHelper
    ) -> bool:
        """Download a single input file."""
        # Handle message object directly
        if (
            hasattr(link, "document")
            or hasattr(link, "video")
            or hasattr(link, "audio")
        ):
            if link.document or link.video or link.audio:
                await TelegramDownloadHelper(self).add_download(
                    link, current_path, self.client
                )
                return True
            return False

        # Handle string inputs
        if isinstance(link, str):
            if is_telegram_link(link):
                message = await self.get_tg_link_message(link)
                if message and (message.document or message.video or message.audio):
                    await TelegramDownloadHelper(self).add_download(
                        message, current_path, self.client
                    )
                    return True
                LOGGER.warning(f"Invalid or empty TG link: {link}")
                return False

            if is_url(link):
                self.link = link
                await add_aria2_download(self, current_path, [], None, None)
                return True

        LOGGER.warning(f"Unknown input type: {type(link)}")
        return False

    async def on_download_complete(self):
        """Handle download completion and trigger merge."""
        self.current_batch_files += 1

        if self.current_batch_files < self.total_batch_files:
            LOGGER.info(
                f"Download complete: {self.current_batch_files}/{self.total_batch_files}"
            )
            return

        LOGGER.info("All downloads complete. Starting merge...")

        # Collect all downloaded files
        input_files = await self._collect_input_files()

        if len(input_files) < 2:
            await self.on_upload_error(
                f"❌ Need at least 2 files to merge. Found: {len(input_files)}"
            )
            return

        input_files.sort()
        LOGGER.info(f"Merging {len(input_files)} files")

        # Calculate total size for byte-based status
        self.size = sum(ospath.getsize(f) for f in input_files)

        # Create FFMpeg concat input file
        input_txt_path = f"{self.dir}/input.txt"
        await self._create_concat_file(input_txt_path, input_files)

        # Setup FFMpeg status
        from bot.helper.mirror_leech_utils.status_utils.merge_status import (
            MergeStatus,
        )

        ffmpeg = FFMpeg(self)
        async with task_dict_lock:
            if self.mid in task_dict:
                self.gid = task_dict[self.mid].gid()
            task_dict[self.mid] = MergeStatus(self, ffmpeg, self.gid)

        await send_status_message(self.message)

        # Determine output name
        if not self.output_name:
            self.output_name = await self._generate_smart_name(input_files)

        # Apply suffix if provided
        if self.name_subfix:
            name, ext = ospath.splitext(self.output_name)
            self.output_name = f"{name} {self.name_subfix}{ext}"

        self.name = self.output_name
        self.subname = ""

        # Check for ASS subtitles and adjust container
        self.name = await self._adjust_container_for_codecs(input_files)

        output_file = f"{self.dir}/{self.name}"

        # Build FFMpeg command
        cmd = self._build_ffmpeg_command(input_txt_path, output_file)
        LOGGER.info(f"Running Merge CMD: {' '.join(cmd)}")

        # Calculate total duration
        total_duration = await self._calculate_total_duration(input_files)

        # Execute merge
        result = await ffmpeg.metadata_watermark_cmds(
            cmd, output_file, total_duration
        )

        if result:
            # Cleanup all temporary files and folders
            await self._cleanup_files()
            await super().on_download_complete()
        else:
            await self.on_upload_error("❌ Merge Failed. Check logs for details.")

    async def _collect_input_files(self) -> list:
        """Collect all downloaded input files."""
        input_files = []
        for i in range(self.total_batch_files):
            input_dir = ospath.join(self.dir, str(i))
            if ospath.isdir(input_dir):
                for root, _, files in await sync_to_async(walk, input_dir):
                    for file in files:
                        if not file.endswith((".aria2", ".!qB")):
                            input_files.append(ospath.join(root, file))
        return input_files

    async def _create_concat_file(self, path: str, files: list):
        """Create FFMpeg concat input file."""
        with open(path, "w", encoding="utf-8") as f:
            for file in files:
                # FFmpeg concat requires forward slashes and escaped single quotes
                abs_path = ospath.abspath(file).replace("\\", "/")
                escaped_path = abs_path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

    async def _generate_smart_name(self, input_files: list) -> str:
        """Generate smart output name based on input files."""
        try:
            # Strip [n/m] prefixes if present
            input_filenames = []
            for f in input_files:
                name = ospath.basename(f)
                input_filenames.append(re.sub(r"^\[\d+/\d+\]\s*", "", name))

            # Patterns for series detection
            pattern_se = re.compile(r"(.*?)S(\d+)\s*E(\d+)", re.IGNORECASE)
            pattern_ep = re.compile(r"(.*?)Episode\s*(\d+)", re.IGNORECASE)
            pattern_part = re.compile(r"(.*?)(?:Part|Pt)\.?\s*(\d+)", re.IGNORECASE)

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
                    season = "01"
                    episodes.append(int(match.group(2)))
                elif match := pattern_part.search(fname):
                    series_name = match.group(1).replace(".", " ").strip()
                    episodes.append(int(match.group(2)))

            if series_name and episodes:
                episodes.sort()
                start_ep = episodes[0]
                end_ep = episodes[-1]

                if season:
                    output_name = (
                        f"{series_name} S{season}E{start_ep:02d}-E{end_ep:02d}.mp4"
                    )
                else:
                    output_name = f"{series_name} Part{start_ep}-{end_ep}.mp4"

                LOGGER.info(f"Smart Renaming: {output_name}")
                return output_name

        except Exception as e:
            LOGGER.error(f"Smart renaming failed: {e}")

        # Fallback to first file name
        return ospath.basename(input_files[0])

    async def _adjust_container_for_codecs(self, input_files: list) -> str:
        """Adjust container format based on codecs present."""
        has_ass = False

        for file in input_files:
            try:
                codecs = await get_codec_info(file)
                if "ass" in codecs or "ssa" in codecs:
                    has_ass = True
                    break
                if "subrip" in codecs or "srt" in codecs:
                    pass
            except Exception as e:
                LOGGER.warning(f"Could not get codec info for {file}: {e}")

        name = self.output_name

        # Use MKV for ASS/SSA subtitles
        if has_ass:
            if not name.lower().endswith(".mkv"):
                base_name = ospath.splitext(name)[0]
                name = f"{base_name}.mkv"
        elif not name.lower().endswith((".mp4", ".mkv")):
            name += ".mp4"

        return name

    def _build_ffmpeg_command(self, input_txt: str, output_file: str) -> list:
        """Build FFMpeg merge command."""
        return [
            "xtra",
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-fflags",
            "+genpts",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            input_txt,
            "-map",
            "0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-metadata",
            f"title={self.name}",
            output_file,
        ]

    async def _calculate_total_duration(self, input_files: list) -> float:
        """Calculate total duration of all input files."""
        total_duration = 0
        for file in input_files:
            try:
                duration = (await get_media_info(file))[0]
                total_duration += duration
            except Exception as e:
                LOGGER.warning(f"Could not get duration for {file}: {e}")
        return total_duration

    async def _cleanup_files(self):
        """Clean up all temporary files and folders after merge."""
        # Only keep the output file in the download directory
        for item in await listdir(self.dir):
            if item == self.name:
                continue
            item_path = ospath.join(self.dir, item)
            try:
                if ospath.isdir(item_path):
                    await sync_to_async(rmtree, item_path, ignore_errors=True)
                else:
                    await remove(item_path)
            except Exception as e:
                LOGGER.warning(f"Could not remove {item_path}: {e}")


async def merge(client, message):
    """Entry point for /merge command."""
    from bot.helper.ext_utils.bulk_links import extract_bulk_links

    bulk = await extract_bulk_links(message, "0", "0")
    if len(bulk) > 1:
        await Merge(client, message).init_bulk(
            message.text.split("\n")[0].split(), 0, 0, Merge
        )
    else:
        bot_loop.create_task(Merge(client, message).new_event())


async def merge_done(client, message):
    """Handle /mdone command to complete merge session."""
    user_id = message.from_user.id

    if user_id not in MERGE_SESSIONS:
        await send_message(
            message,
            f"❌ No active merge session!\n"
            f"Use /{BotCommands.MergeCommand[0]} to start one.",
        )
        return

    session = MERGE_SESSIONS[user_id]

    if len(session["inputs"]) < 2:
        await send_message(
            message,
            "❌ Need at least 2 files to merge!\n"
            f"Current: {len(session['inputs'])}/20",
        )
        return

    # Create listener with session data
    listener = Merge(client, message)
    listener.inputs = session["inputs"]
    listener.total_batch_files = len(listener.inputs)

    # Clean up session
    del MERGE_SESSIONS[user_id]

    # Parse arguments from /mdone command
    text = message.text.split(maxsplit=1)
    if len(text) > 1:
        args = {"-n": "", "-up": "", "-rcf": ""}
        input_args = text[1].split()

        if "-n" in input_args:
            arg_parser(input_args, args)
            if args["-n"]:
                listener.output_name = args["-n"]
            if args["-up"]:
                listener.up_dest = args["-up"]
            if args["-rcf"]:
                listener.rc_flags = args["-rcf"]
        else:
            # Treat raw text as suffix
            listener.name_subfix = text[1].strip()

    await send_message(
        message,
        f"🔄 Merge Started with {listener.total_batch_files} files...",
    )

    try:
        await listener.before_start()
        await listener._proceed_to_download()
        await send_status_message(message)
    except Exception as e:
        LOGGER.error(f"Merge error: {e}")
        await send_message(message, f"❌ Error: {e}")


async def merge_session_handler(client, message):
    """Handle incoming media messages for active merge sessions."""
    user_id = message.from_user.id

    if user_id not in MERGE_SESSIONS:
        return

    # Check if message has media
    media = message.document or message.video or message.audio
    if not media:
        return

    session = MERGE_SESSIONS[user_id]

    if len(session["inputs"]) >= 20:
        await send_message(
            message,
            f"⚠️ Merge Limit Reached (20/20)!\n"
            f"Use /{BotCommands.MdoneCommand[0]} to start.",
        )
        return

    # Check for duplicate
    for existing in session["inputs"]:
        if hasattr(existing, "id") and hasattr(message, "id"):
            if existing.id == message.id:
                await send_message(message, "⚠️ This file is already added!")
                return

    # Add message to session inputs
    session["inputs"].append(message)
    count = len(session["inputs"])

    if count == 20:
        # Auto start at limit
        listener = Merge(client, session["message"])
        listener.inputs = session["inputs"]
        listener.total_batch_files = 20
        del MERGE_SESSIONS[user_id]

        await send_message(message, "✅ Limit reached (20/20). Starting Merge...")
        try:
            await listener.before_start()
            await listener._proceed_to_download()
            await send_status_message(message)
        except Exception as e:
            LOGGER.error(f"Auto-merge error: {e}")
            await send_message(message, f"❌ Error: {e}")
    else:
        remaining = 20 - count
        await send_message(
            message,
            f"✅ Added: {count}/20 ({remaining} slots remaining)\n"
            f"Send more or use /{BotCommands.MdoneCommand[0]}",
        )


async def merge_cancel(client, message):
    """Cancel active merge session."""
    user_id = message.from_user.id

    if user_id in MERGE_SESSIONS:
        del MERGE_SESSIONS[user_id]
        await send_message(message, "✅ Merge session cancelled.")
    else:
        await send_message(message, "❌ No active merge session to cancel.")


def get_merge_session_info(user_id: int) -> dict | None:
    """Get merge session info for a user."""
    return MERGE_SESSIONS.get(user_id)
