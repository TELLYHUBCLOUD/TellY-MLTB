from asyncio import Event, create_task, wait_for, TimeoutError
from functools import partial
from os import makedirs, walk
from os import path as ospath
from re import search as re_search
from time import time

from aiofiles import open as aiopen
from aiofiles.os import path as aiopath
from aiofiles.os import remove
from pyrogram.filters import regex, user
from pyrogram.handlers import CallbackQueryHandler

from bot import DOWNLOAD_DIR, LOGGER, bot_loop, task_dict, task_dict_lock, user_data
from bot.core.aeon_client import TgClient
from bot.core.config_manager import Config
from bot.helper.aeon_utils.access_check import error_check
from bot.helper.ext_utils.bot_utils import (
    arg_parser,
    new_task,
    sync_to_async,
)
from bot.helper.ext_utils.files_utils import get_path_size, clean_download
from bot.helper.ext_utils.links_utils import is_telegram_link, is_url
from bot.helper.ext_utils.media_utils import (
    FFMpeg,
    get_remote_media_info,
    get_streams,
)
from bot.helper.ext_utils.status_utils import get_readable_time
from bot.helper.listeners.task_listener import TaskListener
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import (
    auto_delete_message,
    delete_message,
    edit_message,
    get_tg_link_message,
    send_message,
    send_status_message,
    get_file_info,
)


class EncodeSelection:
    QUALITY_OPTIONS = ["Original", "1080p", "720p", "576p", "480p", "360p", "240p", "144p"]
    CONVERT_OPTIONS = ["mp4", "mkv", "mov", "avi", "webm"]
    TIMEOUT = 120  # Increased timeout for complex operations

    def __init__(self, listener, streams=None):
        self.listener = listener
        self.streams = streams or []
        self.user_id = listener.user_id
        user_dict = user_data.get(self.user_id, {})
        
        # Initialize settings with fallbacks to config
        self.quality = user_dict.get("VIDEO_QUALITY", Config.VIDEO_QUALITY)
        self.mode = user_dict.get("VIDEO_EXT", Config.VIDEO_EXT)
        self.watermark = user_dict.get("WATERMARK_KEY", Config.WATERMARK_KEY)
        self.metadata = user_dict.get("METADATA_KEY", Config.METADATA_KEY)
        self.remove_audio = user_dict.get("REMOVE_AUDIO", Config.REMOVE_AUDIO)
        self.remove_subs = user_dict.get("REMOVE_SUBS", Config.REMOVE_SUBS)
        
        # Stream maps initialization
        self.audio_map = {stream["index"]: True for stream in self.streams 
                          if stream.get("codec_type") == "audio"}
        self.sub_map = {stream["index"]: True for stream in self.streams 
                        if stream.get("codec_type") == "subtitle"}
        
        self.is_cancelled = False
        self.is_extract = False
        self.event = Event()
        self._reply_to = None
        self._timeout = 60
        self._start_time = time()
        self.stype = None

    async def get_selection(self) -> Tuple[Optional[str], Dict, Dict, Optional[str]]:
        """Main entry point for selection UI"""
        await self.main_menu()
        handler = self._setup_handler()
        
        try:
            await wait_for(self.event.wait(), timeout=self.TIMEOUT)
        except TimeoutError:
            await self._handle_timeout()
        finally:
            self.listener.client.remove_handler(*handler)

        if self.is_cancelled:
            await self._cleanup()
            return None, {}, {}, None
        
        return self.quality, self.audio_map, self.sub_map, self.mode

    def _setup_handler(self):
        """Setup callback handler with proper scoping"""
        pfunc = partial(select_encode_options, obj=self)
        return self.listener.client.add_handler(
            CallbackQueryHandler(
                pfunc, 
                filters=regex("^enc") & user(self.user_id)
            ),
            group=-1
        )

    async def _handle_timeout(self):
        """Handle UI timeout with proper cleanup"""
        if self._reply_to:
            await edit_message(
                self._reply_to,
                "Selection timed out after 2 minutes. Task cancelled."
            )
            await auto_delete_message(self._reply_to, 10)
        self.is_cancelled = True
        self.event.set()

    async def _cleanup(self):
        """Cleanup UI messages"""
        if self._reply_to:
            await delete_message(self._reply_to)

    async def main_menu(self):
        buttons = ButtonMaker()
        buttons.data_button("SplitOptions.SUBTITLE_SYNC", "enc subsync")
        buttons.data_button("SplitOptions.WATERMARK", "enc watermark")
        buttons.data_button("SplitOptions.METADATA", "enc metadata")
        buttons.data_button("SplitOptions.TRIM", "enc trim")
        buttons.data_button("SplitOptions.RENAME", "enc rename")
        
        buttons.data_button("SplitOptions.COMPRESS", "enc compress")
        buttons.data_button("SplitOptions.CONVERT", "enc convert")
        
        if self.streams:
            buttons.data_button("SplitOptions.EXTRACT", "enc extract")
            buttons.data_button("SplitOptions.REMOVE_STREAM", "enc remove_stream")
        else:
            buttons.data_button("SplitOptions.REMOVE_AUDIO", "enc rem_audio")
            buttons.data_button("SplitOptions.REMOVE_SUBS", "enc rem_sub")
        
        buttons.data_button("ButtonTitles.DONE", "enc done")
        buttons.data_button("ButtonTitles.CANCEL", "enc cancel")

        msg_text = (
            f"<b>Video Tool Settings</b>\n"
            f"Quality: {self.quality}\n"
            f"Convert: {self.mode}\n"
            f"Timeout: {get_readable_time(self._timeout - (time() - self._start_time))}\n"
        )
        
        markup = buttons.build_menu(2)
        if not self._reply_to:
            self._reply_to = await send_message(
                self.listener.message, msg_text, markup
            )
        else:
            await edit_message(self._reply_to, msg_text, markup)

    async def compress_subbuttons(self):
        buttons = ButtonMaker()
        icon_map = {"audio": "🔊", "subtitle": "💬"}
        
        for stream in self.streams:
            if stream.get("codec_type") != stream_type:
                continue
                
            idx = stream["index"]
            lang = stream.get("tags", {}).get("language", "und")
            is_active = self.audio_map.get(idx) if stream_type == "audio" else self.sub_map.get(idx)
            status_icon = "✅" if is_active else "❌"
            
            buttons.data_button(
                f"{status_icon} {icon_map[stream_type]} {lang.upper()} (#{idx})",
                f"enc toggle_{stream_type} {idx}"
            )
        
        buttons.data_button("ButtonTitles.BACK", "enc done")
        buttons.data_button("ButtonTitles.DONE", "enc done")
        await edit_message(self._reply_to, title, buttons.build_menu(1))

    async def streams_subbuttons(self, stype: Optional[str] = None):
        """Handle stream selection UI"""
        self.stype = stype
        buttons = ButtonMaker()
        if self.streams:
            for stream in self.streams:
                idx = stream["index"]
                ctype = stream["codec_type"]
                if ctype in ["audio", "subtitle"]:
                    if stype and ctype != stype:
                        continue
                    lang = stream.get("tags", {}).get("language", "und")
                    icon = "✅"
                    if ctype == "audio":
                        if not self.audio_map.get(idx, True):
                            icon = "❌"
                        btn_data = f"enc toggle_audio {idx}"
                    else:
                        if not self.sub_map.get(idx, True):
                            icon = "❌"
                        btn_data = f"enc toggle_sub {idx}"
                    buttons.data_button(
                        f"{icon} {ctype.capitalize()}: {lang}", btn_data
                    )
        else:
            # Generic stream removal menu
            buttons = ButtonMaker()
            buttons.data_button(
                f"{'✅' if not self.remove_audio else '❌'} Remove All Audio", 
                "enc toggle_audio 0"
            )
            buttons.data_button(
                f"{'✅' if not self.remove_subs else '❌'} Remove All Subtitles", 
                "enc toggle_sub 0"
            )
            buttons.data_button("ButtonTitles.BACK", "enc done")
            await edit_message(self._reply_to, "Stream Removal Options", buttons.build_menu(1))

    async def get_text_input(self, action: str) -> Optional[str]:
        """Unified text input handler with validation"""
        prompts = {
            "rename": "Send new filename (with extension):",
            "trim": "Send trim time (format: 00:00:05 or 00:00:05-00:00:10):",
            "watermark": "Send watermark text:",
            "metadata": "Send metadata title:",
            "subsync": "Send sync offset in seconds (e.g., 2.5 or -1.2):",
            "mux_va": "Send Telegram link or reply to audio file:",
            "mux_vs": "Send Telegram link or reply to subtitle file:",
        }
        
        validator = {
            "trim": self._validate_trim,
            "subsync": self._validate_subsync,
            "rename": self._validate_filename,
        }.get(action, lambda x: (True, x))

        await edit_message(self._reply_to, prompts[action])
        result = await self._capture_user_input(60)
        
        if result:
            is_valid, value = validator(result)
            if is_valid:
                return value
            await send_message(self.listener.message, f"Invalid input: {value}")
        return None

    async def _capture_user_input(self, timeout: int = 30) -> Optional[str]:
        """Generic user input capture with timeout"""
        user_input = Event()
        result = [None]

        async def func(_, msg):
            if msg.text:
                result[0] = msg.text.strip()
            elif hasattr(msg, 'document') and msg.document:
                result[0] = msg
            elif hasattr(msg, 'link') and msg.link:
                result[0] = msg.link
            elif msg.reply_to_message:
                if hasattr(msg.reply_to_message, 'document'):
                    result[0] = msg.reply_to_message
                elif msg.reply_to_message.text:
                    result[0] = msg.reply_to_message.text

            user_input.set()
            await delete_message(msg)

        handler = self.listener.client.add_handler(
            MessageHandler(input_handler, filters=user(self.user_id)),
            group=-1
        )
        
        try:
            await wait_for(user_input.wait(), timeout=timeout)
            return result[0]
        except TimeoutError:
            await send_message(self.listener.message, "Input timed out. Operation cancelled.")
        finally:
            self.listener.client.remove_handler(*handler)
        return None

    # Validation methods
    def _validate_trim(self, value: str) -> Tuple[bool, str]:
        """Validate trim format"""
        if not re_search(r'^(\d{2}:\d{2}:\d{2})(?:-(\d{2}:\d{2}:\d{2}))?$', value):
            return False, "Invalid trim format. Use HH:MM:SS or HH:MM:SS-HH:MM:SS"
        return True, value

    def _validate_subsync(self, value: str) -> Tuple[bool, str]:
        """Validate subsync offset"""
        try:
            float(value)
            return True, value
        except ValueError:
            return False, "Invalid number format. Use decimal like 2.5 or -1.2"

    def _validate_filename(self, value: str) -> Tuple[bool, str]:
        """Validate and sanitize filename"""
        if not value or '/' in value or '\\' in value:
            return False, "Invalid filename characters"
        return True, value


@new_task
async def select_encode_options(_, query, obj: EncodeSelection):
    """Centralized callback handler for selection UI"""
    data = query.data.split()
    await query.answer()
    
    actions = {
        "compress": obj.compress_subbuttons,
        "convert": obj.convert_subbuttons,
        "qual": lambda: setattr(obj, 'quality', data[2]) or obj.main_menu(),
        "conv_ext": lambda: setattr(obj, 'mode', data[2]) or obj.main_menu(),
        "rename": partial(obj.get_text_input, "rename"),
        "trim": partial(obj.get_text_input, "trim"),
        "watermark": partial(obj.get_text_input, "watermark"),
        "metadata": partial(obj.get_text_input, "metadata"),
        "subsync": partial(obj.get_text_input, "subsync"),
        "mux_va": partial(obj.get_text_input, "mux_va"),
        "mux_vs": partial(obj.get_text_input, "mux_vs"),
        "extract": lambda: setattr(obj, 'is_extract', True) or obj.streams_subbuttons(),
        "remove_stream": obj.streams_subbuttons,
        "rem_audio": lambda: obj.streams_subbuttons("audio"),
        "rem_sub": lambda: obj.streams_subbuttons("subtitle"),
        "toggle_audio": lambda: _toggle_stream(obj, "audio", int(data[2])),
        "toggle_sub": lambda: _toggle_stream(obj, "subtitle", int(data[2])),
        "cancel": lambda: setattr(obj, 'is_cancelled', True) or obj.event.set(),
        "done": lambda: obj.event.set() or delete_message(query.message),
    }
    
    action = actions.get(data[1])
    if action:
        if callable(action):
            result = action()
            if hasattr(result, '__await__'):
                await result
        else:
            action()
    else:
        LOGGER.warning(f"Unhandled callback action: {data[1]}")


def _toggle_stream(obj: EncodeSelection, stream_type: str, index: int):
    """Toggle stream selection state"""
    if stream_type == "audio":
        if index in obj.audio_map:
            obj.audio_map[index] = not obj.audio_map[index]
        else:
            obj.remove_audio = not obj.remove_audio
    else:
        if index in obj.sub_map:
            obj.sub_map[index] = not obj.sub_map[index]
        else:
            obj.remove_subs = not obj.remove_subs
    create_task(obj.streams_subbuttons(obj.stype))


class Encode(TaskListener):
    def __init__(self, client, message, **kwargs):
        self.message = message
        self.client = client
        self.quality = ""
        self.remove_audio = False
        self.remove_subs = False
        self.audio_map = {}
        self.sub_map = {}
        self.mode = "Original"
        self.trim_start = ""
        self.trim_end = ""
        self.watermark_text = ""
        self.subsync_offset = ""
        self.new_name = ""
        self.has_metadata_selection = False
        self.mux_link = ""
        self.mux_type = ""
        self.metadata = ""
        self.is_extract = False
        super().__init__()
        self.is_leech = kwargs.get("is_leech", True)
        self.is_auto = kwargs.get("is_auto", False)
        self.bulk = []
        self.multi = 0
        self.options = ""
        self.same_dir = {}
        self.multi_tag = ""
        
        # Processing options
        self.quality = kwargs.get("quality", "")
        self.remove_audio = kwargs.get("remove_audio", False)
        self.remove_subs = kwargs.get("remove_subs", False)
        self.mode = kwargs.get("mode", "Original")
        self.trim_start = kwargs.get("trim_start", "")
        self.trim_end = kwargs.get("trim_end", "")
        self.watermark_text = kwargs.get("watermark_text", "")
        self.subsync_offset = kwargs.get("subsync_offset", "")
        self.new_name = kwargs.get("new_name", "")
        self.mux_link = kwargs.get("mux_link", "")
        self.mux_type = kwargs.get("mux_type", "")
        self.metadata = kwargs.get("metadata", "")
        self.is_extract = kwargs.get("is_extract", False)
        
        # Internal state
        self.audio_map = {}
        self.sub_map = {}
        self.has_metadata_selection = False
        self.target_file = None

    async def new_event(self):
        text = self.message.text.split("\n")
        input_list = text[0].split(" ")
        error_msg, error_button = await error_check(self.message)
        if error_msg:
            await self._handle_error(error_msg, error_button)
            return

        args = self._parse_arguments()
        await self.get_tag(self.message.text.split("\n"))

        # Handle bulk/multi processing
        if self._should_handle_bulk(args):
            await self._init_bulk_processing(args)
            return

        await self._handle_multi_links(args)
        await self._resolve_input_source(args)
        
        if not self.link:
            await send_message(self.message, "No valid media source found. Provide a link or reply to media.")
            return

        await self._process_video(args)

    def _parse_arguments(self) -> Dict:
        """Parse command arguments with validation"""
        input_list = self.message.text.split("\n")[0].split()
        args = {
            "link": "",
            "-i": 0,
            "-n": "",
            "-up": "",
            "-rcf": "",
            "-q": "",
            "-an": False,
            "-sn": False,
            "-b": False,
        }

        arg_parser(input_list[1:], args)
        
        # Validate quality parameter
        if args["-q"] and args["-q"] not in EncodeSelection.QUALITY_OPTIONS:
            raise ValueError(f"Invalid quality option. Choose from: {', '.join(EncodeSelection.QUALITY_OPTIONS)}")
        
        return args

    async def _resolve_input_source(self, args: Dict):
        """Resolve input source from link, reply, or bulk"""
        self.link = args["link"]
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
            await self.init_bulk(input_list, bulk_start, bulk_end, Encode)
            return None

        await self.run_multi(input_list, Encode)

        self.name = args["-n"]
        self.up_dest = args["-up"]
        self.rc_flags = args["-rcf"]
        self.quality = args["-q"]
        self.remove_audio = args["-an"]
        self.remove_subs = args["-sn"]

        all_links = []
        for line in text:
            line = line.strip()
            if not line:
                continue
            if is_telegram_link(line):
                match = re_search(
                    r"(https?://t\.me/(?:c/)?(?:[\w\d]+)/)(\d+)-(\d+)", line
                )
                if match:
                    base = match.group(1)
                    start = int(match.group(2))
                    end = int(match.group(3))
                    if start <= end:
                        for i in range(start, end + 1):
                            all_links.append(f"{base}{i}")
                    continue
            if is_url(line) or is_telegram_link(line):
                all_links.append(line)

        if len(all_links) > 1:
            args["link"] = all_links[0]
            for other_link in all_links[1:]:
                new_text = (
                    f"/{BotCommands.VideoToolCommand[0]} {other_link} "
                    + " ".join(input_list[1:])
                )
                new_msg = await self.client.get_messages(
                    self.message.chat.id, self.message.id
                )
                new_msg.text = new_text
                bot_loop.create_task(Encode(self.client, new_msg).new_event())
            self.link = all_links[0]

        if not self.link and (reply_to := self.message.reply_to_message):
            if reply_to.document or reply_to.video or reply_to.audio:
                self.link = reply_to
            elif reply_to.text:
                self.link = reply_to.text.split("\n", 1)[0].strip()

        if isinstance(self.link, str) and is_telegram_link(self.link):
            try:
                reply_to, _session = await get_tg_link_message(
                    self.link, self.message.from_user.id
                )
                if reply_to:
                    self.link = reply_to
            except Exception as e:
                await self._handle_error(f"Failed to resolve Telegram link: {str(e)}")
                self.link = None

    async def _process_video(self, args: Dict):
        """Main video processing workflow"""
        media_info = await self._fetch_media_metadata()
        if not media_info:
            return

        # Initialize selection UI
        selector = self._initialize_selector(media_info, args)
        qual, audio_map, sub_map, mode = await selector.get_selection()
        
        if selector.is_cancelled:
            await clean_download(self.dir)
            return
        
        # Apply selections
        self._apply_selections(selector, qual, audio_map, sub_map, mode)
        await self.before_start()
        await self._start_download()

    async def _fetch_media_metadata(self) -> Optional[List[Dict]]:
        """Fetch media metadata with size constraints"""
        if not self.link:
            await send_message(self.message, "No link or reply found.")
            return None

        if hasattr(self.link, "id"):
            media = self.link.document or self.link.video or self.link.audio
            link_info = f"TG Message: {self.link.id} (File: {media.file_name if media else 'Unknown'})"
        else:
            link_info = str(self.link)

        LOGGER.info(f"Video Tool Request: Link: {link_info}")

        streams = []
        if (
            (isinstance(self.link, str) and is_url(self.link))
            or hasattr(self.link, "document")
            or hasattr(self.link, "video")
            or hasattr(self.link, "audio")
        ):
            wait_msg = await send_message(self.message, "⏳ Fetching Metadata...")
            if isinstance(self.link, str) and is_url(self.link):
                return await get_remote_media_info(self.link)
            
            # Handle Telegram media with size check
            media = self.link.document or self.link.video or self.link.audio
            if not media:
                await send_message(self.message, "Unsupported media type. Provide video, audio, or document.")
                return None

            if media.file_size > self.MAX_FILE_SIZE:
                await send_message(
                    self.message,
                    f"File too large for metadata analysis (>4GB). "
                    f"Processing will use default settings."
                )
                return None

            return await self._fetch_tg_metadata(media)
        finally:
            await delete_message(wait_msg)

    async def _fetch_tg_metadata(self, media) -> List[Dict]:
        """Fetch metadata for Telegram files with partial download"""
        path = f"{DOWNLOAD_DIR}Metadata/"
        await sync_to_async(makedirs, path, exist_ok=True)
        file_path = ospath.join(path, f"{self.mid}_{media.file_name or 'metadata'}")
        
        try:
            # Stream only first 5MB for metadata
            downloaded = 0
            MAX_BYTES = 5 * 1024 * 1024
            
            async with aiopen(file_path, 'wb') as f:
                async for chunk in TgClient.bot.stream_media(media, limit=10):
                    if downloaded + len(chunk) > MAX_BYTES:
                        chunk = chunk[:MAX_BYTES - downloaded]
                    await f.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= MAX_BYTES:
                        break
            
            return await get_streams(file_path)
        finally:
            if await aiopath.exists(file_path):
                await aioremove(file_path)

    async def on_download_complete(self):
        """Post-download processing workflow"""
        if not await self._find_target_file():
            await self.on_upload_error("No valid video file found in download directory")
            return

        file_path = target_file

        # Resolve MUX Link if present
        mux_file = None
        if self.mux_link:
            mux_path = f"{self.dir}/mux/"
            await sync_to_async(makedirs, mux_path, exist_ok=True)
            if is_telegram_link(self.mux_link):
                try:
                    msg, client = await get_tg_link_message(
                        self.mux_link, self.user_id
                    )
                    if not msg:
                        await self.on_upload_error(
                            "MUX TG Download Error: Message not found or access denied."
                        )
                        return

                    if isinstance(msg, list):
                        msg, client = await get_tg_link_message(msg[0], self.user_id)
                        if not msg:
                            await self.on_upload_error(
                                "MUX TG Download Error: Could not resolve first link in range."
                            )
                            return

                    media = msg.document or msg.video or msg.audio or msg.voice
                    if media:
                        mux_file = await client.download_media(media, mux_path)
                        if mux_file:
                            LOGGER.info(f"MUX secondary file downloaded: {mux_file}")
                        else:
                            await self.on_upload_error(
                                "MUX TG Download Error: client.download_media returned None."
                            )
                            return
                    else:
                        await self.on_upload_error(
                            "MUX TG Download Error: No media (video/audio/sub) found in the provided Telegram link."
                        )
                        return
                except Exception as e:
                    await self.on_upload_error(f"MUX TG Download Error: {e}")
                    return
            elif is_url(self.mux_link):
                try:
                    from httpx import AsyncClient

                    async with (
                        AsyncClient(follow_redirects=True, verify=False) as client,
                        client.stream("GET", self.mux_link) as response,
                    ):
                        if response.status_code == 200:
                            filename = (
                                self.mux_link.split("/")[-1].split("?")[0]
                                or "mux_file"
                            )
                            mux_file = ospath.join(mux_path, filename)
                            async with aiopen(mux_file, "wb") as f:
                                async for chunk in response.aiter_bytes():
                                    await f.write(chunk)
                        else:
                            await self.on_upload_error(
                                f"MUX URL HTTP Error: {response.status_code}"
                            )
                            return
                except Exception as e:
                    await self.on_upload_error(f"MUX URL Download Error: {e}")
                    return
            else:
                await self.on_upload_error(
                    "MUX Error: Invalid link provided. Must be a Telegram link or a direct URL."
                )
                return

        try:
            output_file = await self._process_with_ffmpeg(mux_file)
            if not output_file or not await aiopath.exists(output_file):
                raise Exception("Processing failed - output file not created")
            
            # Cleanup and proceed to upload
            await self._cleanup_temp_files(mux_file)
            self.name = ospath.basename(output_file)
            await super().on_download_complete()
        except Exception as e:
            LOGGER.exception(f"Processing failed: {str(e)}")
            await self.on_upload_error(f"Video processing failed: {str(e)}")
        finally:
            await self._cleanup_temp_files(mux_file)

    async def _find_target_file(self) -> bool:
        """Find largest video file in download directory"""
        video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
        largest_file = None
        max_size = 0

        async for entry in self._walk_async(self.dir):
            if entry.is_file():
                ext = ospath.splitext(entry.name)[1].lower()
                if ext in video_extensions:
                    size = await get_path_size(entry.path)
                    if size > max_size:
                        max_size = size
                        largest_file = entry.path

        if largest_file:
            self.target_file = largest_file
            return True
        return False

    async def _walk_async(self, path: str):
        """Async directory walker"""
        for root, dirs, files in await sync_to_async(oswalk, path):
            for name in files:
                yield FileEntry(ospath.join(root, name), name)
            for name in dirs:
                async for entry in self._walk_async(ospath.join(root, name)):
                    yield entry

    async def _process_with_ffmpeg(self, mux_file: Optional[str]) -> Optional[str]:
        """Build and execute FFmpeg command"""
        ffmpeg = FFMpeg(self)
        status = VideoToolsStatus(self, ffmpeg)
        
        async with task_dict_lock:
            task_dict[self.mid] = status
        
        await send_status_message(self.message)
        
        cmd = self._build_ffmpeg_command(mux_file)
        output_file = ospath.join(self.dir, self._get_output_filename())
        
        LOGGER.info(f"Executing FFmpeg command: {' '.join(cmd)}")
        success = await ffmpeg.execute(cmd, self.target_file, output_file)
        
        if not success:
            raise Exception("FFmpeg processing failed (check logs for details)")
        
        return output_file

    def _build_ffmpeg_command(self, mux_file: Optional[str]) -> List[str]:
        """Construct FFmpeg command based on user selections"""
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1"]
        
        # Input handling
        if self.trim_start:
            cmd.extend(["-ss", self.trim_start])
        if self.trim_end:
            cmd.extend(["-to", self.trim_end])
        cmd.extend(["-i", self.target_file])
        
        if mux_file:
            cmd.extend(["-i", mux_file])

        # Determine output extension early
        out_ext = None
        if self.is_extract:
            # Extract mode
            keep_audio = [idx for idx, k in self.audio_map.items() if k]
            keep_sub = [idx for idx, k in self.sub_map.items() if k]
            if keep_audio:
                out_ext = "m4a"
            elif keep_sub:
                out_ext = "srt"
        elif self.mode in ["mp4", "mkv", "mov", "avi", "webm"]:
            out_ext = self.mode

        if not out_ext:
            out_ext = ospath.splitext(file_path)[1][1:]

        # Video Filter Logic
        vf = []

        if self.quality not in ["Original", "mp4", "mkv", "mov", "avi", "webm"]:
            if self.quality == "1080p":
                vf.append("scale=-2:1080")
            elif self.quality == "720p":
                vf.append("scale=-2:720")
            elif self.quality == "576p":
                vf.append("scale=-2:576")
            elif self.quality == "480p":
                vf.append("scale=-2:480")
            elif self.quality == "360p":
                vf.append("scale=-2:360")
            elif self.quality == "240p":
                vf.append("scale=-2:240")
            elif self.quality == "144p":
                vf.append("scale=-2:144")

        if self.watermark_text:
            vf_filters.append(self._get_watermark_filter())
        
        if self.quality not in ["Original", ""]:
            vf_filters.append(self._get_scale_filter())
        
        if vf_filters:
            cmd.extend(["-vf", ",".join(vf_filters), "-c:v", "libx264"])
        else:
            cmd.extend(["-c:v", "copy"])

        # Stream mapping and codec selection
        cmd.extend(self._get_stream_mapping(mux_file))
        
        # Metadata handling
        if self.metadata or self.tag:
            metadata = self.metadata or self.tag
            cmd.extend([
                "-metadata", f"title={metadata}",
                "-metadata:s:v", f"title={metadata}",
                "-metadata:s:a", f"title={metadata}",
                "-metadata:s:s", f"title={metadata}"
            ])
        
        # Subsync handling
        if self.subsync_offset:
            try:
                offset_val = float(self.subsync_offset)
                cmd.extend(["-itsoffset", str(offset_val)])
            except ValueError:
                LOGGER.warning(f"Invalid subsync offset: {self.subsync_offset}")
        
        return cmd

    def _get_output_filename(self) -> str:
        """Generate output filename based on processing options"""
        base = ospath.splitext(ospath.basename(self.target_file))[0]
        suffix = "_processed"
        
        if self.is_extract:
            suffix = "_extracted"
        elif self.trim_start or self.trim_end:
            suffix = "_trimmed"
        elif self.watermark_text:
            suffix = "_watermarked"
        
        ext = self.mode if self.mode in EncodeSelection.CONVERT_OPTIONS else ospath.splitext(self.target_file)[1][1:]
        return f"{base}{suffix}.{ext}"

    async def _cleanup_temp_files(self, mux_file: Optional[str]):
        """Cleanup temporary files safely"""
        files_to_remove = [self.target_file]
        if mux_file:
            files_to_remove.append(mux_file)
        
        for file_path in files_to_remove:
            try:
                if await aiopath.exists(file_path):
                    await remove(file_path)
                if mux_file and await aiopath.exists(mux_file):
                    await remove(mux_file)
                self.name = out_name
            except Exception as e:
                LOGGER.warning(f"Failed to remove {file_path}: {str(e)}")


async def videotool(client, message):
    """Entry point for video tools command"""
    if len(message.text.split()) == 1:
        await send_message(
            message,
            f"Use format: /{BotCommands.VideoToolCommand[0]} <link> | reply to media\n\n"
            "Available options:\n"
            "-q <quality> : Compression quality\n"
            "-an : Remove all audio\n"
            "-sn : Remove all subtitles\n"
            "-n <name> : Custom output name"
        )
        return

    bot_loop.create_task(Encode(client, message).new_event())


# Supporting classes
class FileEntry:
    __slots__ = ('path', 'name')
    def __init__(self, path: str, name: str):
        self.path = path
        self.name = name
    
    def is_file(self) -> bool:
        return True

class VideoToolsStatus:
    def __init__(self, listener, ffmpeg):
        self.listener = listener
        self.ffmpeg = ffmpeg
        self._processed_bytes = 0
    
    def gid(self) -> str:
        return f"{self.listener.mid}{self.listener.client.me.id}"
    
    async def update(self, processed: int):
        self._processed_bytes = processed
        # Update status message here if needed