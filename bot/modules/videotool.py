from asyncio import Event, create_task, wait_for
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
from bot.helper.ext_utils.files_utils import get_path_size
from bot.helper.ext_utils.links_utils import is_telegram_link, is_url
from bot.helper.ext_utils.media_utils import (
    FFMpeg,
    get_remote_media_info,
    get_streams,
)
from bot.helper.ext_utils.status_utils import get_readable_time
from bot.helper.listeners.task_listener import TaskListener
from bot.helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import (
    auto_delete_message,
    delete_links,
    delete_message,
    edit_message,
    get_tg_link_message,
    send_message,
    send_status_message,
)


@new_task
async def select_encode_options(_, query, obj):
    data = query.data.split()
    message = query.message
    await query.answer()

    if data[1] == "compress":
        await obj.compress_subbuttons()
    elif data[1] == "convert":
        await obj.convert_subbuttons()
    elif data[1] == "main":
        await obj.main_menu()
    elif data[1] == "qual":
        obj.quality = data[2]
        await obj.main_menu()
    elif data[1] == "conv_ext":
        obj.mode = data[2]
        await obj.main_menu()
    elif data[1] == "rename":
        await obj.get_text_input("rename")
    elif data[1] == "trim":
        await obj.get_text_input("trim")
    elif data[1] == "watermark":
        await obj.get_text_input("watermark")
    elif data[1] == "metadata":
        await obj.get_text_input("metadata")
    elif data[1] == "subsync":
        await obj.get_text_input("subsync")
    elif data[1] == "mux_va":
        await obj.get_text_input("mux_va")
    elif data[1] == "mux_vs":
        await obj.get_text_input("mux_vs")
    elif data[1] == "extract":
        obj.is_extract = True
        await obj.streams_subbuttons()
    elif data[1] == "remove_stream":
        await obj.streams_subbuttons()
    elif data[1] == "rem_audio":
        await obj.streams_subbuttons(stype="audio")
    elif data[1] == "rem_sub":
        await obj.streams_subbuttons(stype="subtitle")
    elif data[1] == "toggle_audio":
        index = int(data[2])
        if obj.streams:
            obj.audio_map[index] = not obj.audio_map[index]
        else:
            obj.remove_audio = not obj.remove_audio
        await obj.streams_subbuttons(stype=obj.stype)
    elif data[1] == "toggle_sub":
        index = int(data[2])
        if obj.streams:
            obj.sub_map[index] = not obj.sub_map[index]
        else:
            obj.remove_subs = not obj.remove_subs
        await obj.streams_subbuttons(stype=obj.stype)
    elif data[1] == "cancel":
        await edit_message(message, "Task Cancelled.")
        obj.is_cancelled = True
        obj.event.set()
    elif data[1] == "done":
        await delete_message(message)
        obj.event.set()


class EncodeSelection:
    def __init__(self, listener, streams=None):
        self.listener = listener
        self.streams = streams
        user_dict = user_data.get(listener.user_id, {})
        self.quality = user_dict.get("VIDEO_QUALITY") or Config.VIDEO_QUALITY
        self.mode = user_dict.get("VIDEO_EXT") or Config.VIDEO_EXT
        self.watermark = user_dict.get("WATERMARK_KEY") or Config.WATERMARK_KEY
        self.metadata = user_dict.get("METADATA_KEY") or Config.METADATA_KEY
        self.audio_map = {}
        self.sub_map = {}
        self.remove_audio = user_dict.get("REMOVE_AUDIO", Config.REMOVE_AUDIO)
        self.remove_subs = user_dict.get("REMOVE_SUBS", Config.REMOVE_SUBS)
        self.is_cancelled = False
        self.is_extract = False
        self.event = Event()
        self._reply_to = None
        self._timeout = 60
        self._start_time = time()
        self.stype = None

        if streams:
            for stream in streams:
                if stream["codec_type"] == "audio":
                    self.audio_map[stream["index"]] = True
                elif stream["codec_type"] == "subtitle":
                    self.sub_map[stream["index"]] = True

    async def get_selection(self):
        await self.main_menu()
        pfunc = partial(select_encode_options, obj=self)
        handler = self.listener.client.add_handler(
            CallbackQueryHandler(
                pfunc, filters=regex("^enc") & user(self.listener.user_id)
            ),
            group=-1,
        )
        try:
            await wait_for(self.event.wait(), timeout=self._timeout)
        except Exception:
            if self._reply_to:
                await delete_message(self._reply_to)
        finally:
            self.listener.client.remove_handler(*handler)

        if self.is_cancelled:
            return None, None, None, None

        return self.quality, self.audio_map, self.sub_map, self.mode

    async def main_menu(self):
        buttons = ButtonMaker()
        buttons.data_button("Rename", "enc rename")
        buttons.data_button("Video + Audio", "enc mux_va")
        buttons.data_button("Video + Subtitle", "enc mux_vs")
        buttons.data_button("SubSync", "enc subsync")
        buttons.data_button("Compress", "enc compress")
        buttons.data_button("Convert", "enc convert")
        buttons.data_button("Watermark", "enc watermark")
        buttons.data_button("Metadata", "enc metadata")
        buttons.data_button("Extract", "enc extract")
        buttons.data_button("Trim", "enc trim")
        buttons.data_button("Remove Stream", "enc remove_stream")
        buttons.data_button("Remove Audio", "enc rem_audio")
        buttons.data_button("Remove Subtitle", "enc rem_sub")

        buttons.data_button("Done", "enc done")
        buttons.data_button("Cancel", "enc cancel")

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
        options = [
            "Original",
            "1080p",
            "720p",
            "576p",
            "480p",
            "360p",
            "240p",
            "144p",
        ]
        for opt in options:
            prefix = "✅ " if self.quality == opt else ""
            buttons.data_button(f"{prefix}{opt}", f"enc qual {opt}")
        buttons.data_button("Back", "enc main")
        markup = buttons.build_menu(2)
        await edit_message(self._reply_to, "Select Quality", markup)

    async def convert_subbuttons(self):
        buttons = ButtonMaker()
        options = ["mp4", "mkv", "mov", "avi", "webm"]
        for opt in options:
            prefix = "✅ " if self.mode == opt else ""
            buttons.data_button(f"{prefix}{opt}", f"enc conv_ext {opt}")
        buttons.data_button("Back", "enc main")
        markup = buttons.build_menu(2)
        await edit_message(self._reply_to, "Select Extension", markup)

    async def streams_subbuttons(self, stype=None):
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
            if not stype or stype == "audio":
                a_icon = "❌" if self.remove_audio else "✅"
                buttons.data_button(f"{a_icon} Audio (All)", "enc toggle_audio 0")
            if not stype or stype == "subtitle":
                s_icon = "❌" if self.remove_subs else "✅"
                buttons.data_button(f"{s_icon} Subs (All)", "enc toggle_sub 0")

        buttons.data_button("Back", "enc main")
        buttons.data_button("Done", "enc done")
        markup = buttons.build_menu(1)
        title = "Select Streams to Keep"
        if stype:
            title = f"Select {stype.capitalize()} Streams"
        await edit_message(self._reply_to, title, markup)

    async def get_text_input(self, action):
        from pyrogram.filters import user
        from pyrogram.handlers import MessageHandler

        prompt = {
            "rename": "Send the new name for the file:",
            "trim": "Send trim time (format: 00:00:05-00:00:10):",
            "watermark": "Send the text for the watermark:",
            "metadata": "Send the title for the metadata tag:",
            "subsync": "Send the sync offset (e.g. 2.5 or -1.2):",
            "mux_va": "Send the Telegram link or reply to the Audio file:",
            "mux_vs": "Send the Telegram link or reply to the Subtitle file:",
        }.get(action, "Send input:")

        await edit_message(self._reply_to, prompt)

        user_input = Event()
        result = [None]

        async def func(_, msg):
            if msg.text:
                result[0] = msg.text
            elif hasattr(msg, "link") and msg.link:
                result[0] = msg.link
            elif msg.reply_to_message:
                if hasattr(msg.reply_to_message, "link"):
                    result[0] = msg.reply_to_message.link
                elif msg.reply_to_message.text:
                    result[0] = msg.reply_to_message.text

            user_input.set()
            await delete_message(msg)

        handler = self.listener.client.add_handler(
            MessageHandler(func, filters=user(self.listener.user_id)), group=-1
        )
        try:
            await wait_for(user_input.wait(), timeout=30)
            text = result[0]
            if action == "rename":
                self.listener.new_name = text
            elif action == "trim":
                if text and "-" in text:
                    parts = text.split("-")
                    if len(parts) == 2:
                        self.listener.trim_start, self.listener.trim_end = (
                            parts[0].strip(),
                            parts[1].strip(),
                        )
            elif action == "watermark":
                self.listener.watermark_text = text
            elif action == "metadata":
                self.listener.metadata = text
            elif action == "subsync":
                self.listener.subsync_offset = text
            elif action.startswith("mux_"):
                self.listener.mux_link = text
                self.listener.mux_type = action
        except:
            pass
        finally:
            self.listener.client.remove_handler(*handler)
        await self.main_menu()


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
            "-q": "",
            "-an": False,
            "-sn": False,
            "-b": False,
        }

        arg_parser(input_list[1:], args)

        await self.get_tag(text)

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
                await send_message(self.message, f"ERROR: {e}")
                return None

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
                streams = await get_remote_media_info(self.link)
            else:
                media = self.link.document or self.link.video or self.link.audio
                if media:
                    path = f"{DOWNLOAD_DIR}Metadata/"
                    if not await aiopath.isdir(path):
                        await sync_to_async(makedirs, path, exist_ok=True)

                    des_path = ospath.join(
                        path, f"{self.mid}_{media.file_name or 'temp'}"
                    )
                    try:
                        async for chunk in TgClient.bot.stream_media(media, limit=5):
                            async with aiopen(des_path, "ab") as f:
                                await f.write(chunk)
                        streams = await get_streams(des_path)
                    except Exception as e:
                        LOGGER.error(f"Error fetching TG metadata: {e}")
                    finally:
                        if await aiopath.exists(des_path):
                            await remove(des_path)

            if streams:
                self.has_metadata_selection = True
            await delete_message(wait_msg)

        selector = EncodeSelection(self, streams)
        if self.quality:
            selector.quality = self.quality
        if self.remove_audio and streams:
            for idx in selector.audio_map:
                selector.audio_map[idx] = False
        elif self.remove_audio:
            selector.remove_audio = True
        if self.remove_subs and streams:
            for idx in selector.sub_map:
                selector.sub_map[idx] = False
        elif self.remove_subs:
            selector.remove_subs = True

        if self.is_auto:
            qual, map1, map2, mode = (
                selector.quality,
                selector.audio_map,
                selector.sub_map,
                selector.mode,
            )
        else:
            qual, map1, map2, mode = await selector.get_selection()
        if qual is None:
            return None

        self.quality = qual
        self.mode = mode if mode != "Original" else self.mode
        if streams:
            self.audio_map = map1
            self.sub_map = map2
        else:
            self.remove_audio = selector.remove_audio
            self.remove_subs = selector.remove_subs

        # Copy over user selections
        self.is_extract = selector.is_extract

        try:
            await self.before_start()
        except Exception as e:
            await send_message(self.message, e)
            return None

        await self._proceed_to_download()
        return None

    async def _proceed_to_download(self):
        from bot.helper.mirror_leech_utils.download_utils.telegram_download import (
            TelegramDownloadHelper,
        )

        path = f"{self.dir}/"
        if hasattr(self.link, "download") or not isinstance(self.link, str):
            create_task(
                TelegramDownloadHelper(self).add_download(
                    self.link if not hasattr(self.link, "download") else self.link,
                    path,
                    self.client,
                ),
            )
        elif is_url(self.link):
            create_task(add_aria2_download(self, path, [], None, None))

    async def on_download_complete(self):
        target_file = None
        max_size = 0
        video_extensions = {
            ".mp4",
            ".mkv",
            ".avi",
            ".mov",
            ".webm",
            ".flv",
            ".wmv",
            ".ts",
            ".m4v",
            ".dat",
            ".vob",
            ".3gp",
            ".mpeg",
            ".mpg",
        }

        for root, _, files_list in await sync_to_async(walk, self.dir):
            for file_name in files_list:
                if file_name.endswith((".aria2", ".!qB")) or "mux" in root:
                    continue
                ext = ospath.splitext(file_name)[1].lower()
                if ext in video_extensions:
                    file_path = ospath.join(root, file_name)
                    size = await get_path_size(file_path)
                    if size > max_size:
                        max_size = size
                        target_file = file_path

        if not target_file:
            await self.on_upload_error("No valid video files found.")
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

        ffmpeg = FFMpeg(self)
        from bot.helper.mirror_leech_utils.status_utils.videotools_status import (
            VideoToolsStatus,
        )

        async with task_dict_lock:
            if self.mid in task_dict:
                self.gid = task_dict[self.mid].gid()
            task_dict[self.mid] = VideoToolsStatus(self, ffmpeg, self.gid)

        await send_status_message(self.message)

        # Build FFmpeg Command
        cmd = ["xtra", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1"]

        # Input 1 (Original)
        if self.trim_start:
            cmd.extend(["-ss", self.trim_start])
        if self.trim_end:
            cmd.extend(["-to", self.trim_end])
        cmd.extend(["-i", file_path])

        # Input 2 (MUX)
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
            escaped_text = self.watermark_text.replace("'", "'\\''").replace(
                ":", "\\:"
            )
            vf.append(
                f"drawtext=text='{escaped_text}':x=(w-text_w)/2:y=(h-text_h)/2:fontsize=24:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2"
            )

        # Mapping & Command Building Logic
        if self.is_extract:
            # Extract specific stream
            cmd = ["xtra", "-hide_banner", "-loglevel", "error", "-i", file_path]
            keep_audio = [idx for idx, k in self.audio_map.items() if k]
            keep_sub = [idx for idx, k in self.sub_map.items() if k]

            if keep_audio:
                cmd.extend(
                    ["-map", f"0:{keep_audio[0]}", "-c:a", "copy", "-vn", "-sn"]
                )
            elif keep_sub:
                cmd.extend(
                    ["-map", f"0:{keep_sub[0]}", "-c:s", "copy", "-vn", "-an"]
                )

        elif self.mux_type and mux_file:
            # MUX operation
            if vf:
                cmd.extend(["-vf", ",".join(vf), "-c:v", "libx264"])
            else:
                cmd.extend(["-c:v", "copy"])

            cmd.extend(["-map", "0:v:0"])

            if self.mux_type == "mux_va":
                cmd.extend(["-map", "0:a?", "-map", "1:a:0", "-map", "0:s?"])
            elif self.mux_type == "mux_vs":
                cmd.extend(["-map", "0:a?", "-map", "1:s:0"])
            cmd.extend(["-c:a", "copy", "-c:s", "copy"])

        elif self.has_metadata_selection and self.audio_map:
            # Stream selection with metadata
            if vf:
                cmd.extend(["-vf", ",".join(vf), "-c:v", "libx264"])
            else:
                cmd.extend(["-c:v", "copy"])

            cmd.extend(["-map", "0:v"])
            for idx, keep in self.audio_map.items():
                if keep:
                    cmd.extend(["-map", f"0:{idx}"])
            for idx, keep in self.sub_map.items():
                if keep:
                    cmd.extend(["-map", f"0:{idx}"])
            cmd.extend(["-c:a", "copy", "-c:s", "copy"])

        else:
            # Standard processing
            if vf:
                cmd.extend(["-vf", ",".join(vf), "-c:v", "libx264"])
            else:
                cmd.extend(["-c:v", "copy"])

            if self.remove_audio:
                cmd.append("-an")
            else:
                cmd.extend(["-c:a", "copy"])

            if self.remove_subs:
                cmd.append("-sn")
            else:
                cmd.extend(["-c:s", "copy"])

        # Apply subsync if provided
        if self.subsync_offset and not self.is_extract:
            try:
                offset_val = float(self.subsync_offset)
                cmd.extend(["-itsoffset", str(offset_val)])
            except ValueError:
                LOGGER.warning(f"Invalid subsync offset: {self.subsync_offset}")

        # Apply Metadata Tag if provided
        final_metadata = self.metadata or self.tag
        if final_metadata:
            cmd.extend(["-metadata", f"title={final_metadata}"])
            cmd.extend(["-metadata:s:v", f"title={final_metadata}"])
            cmd.extend(["-metadata:s:a", f"title={final_metadata}"])
            cmd.extend(["-metadata:s:s", f"title={final_metadata}"])

        # Output file setup
        out_name = (
            self.new_name
            or f"{ospath.splitext(ospath.basename(file_path))[0]}_processed.{out_ext}"
        )

        if not out_name.lower().endswith(f".{out_ext.lower()}"):
            out_name = f"{ospath.splitext(out_name)[0]}.{out_ext}"

        output_file = ospath.join(self.dir, out_name)
        cmd.append(output_file)

        LOGGER.info(f"FFmpeg Command: {' '.join(cmd)}")

        res = await ffmpeg.metadata_watermark_cmds(cmd, file_path)

        if res:
            try:
                # Cleanup original and mux files
                if await aiopath.exists(file_path):
                    await remove(file_path)
                if mux_file and await aiopath.exists(mux_file):
                    await remove(mux_file)
                self.name = out_name
            except Exception as e:
                LOGGER.error(f"Error during cleanup: {e}")
            await super().on_download_complete()
        else:
            await self.on_upload_error("Video Processing Failed.")


async def videotool(client, message):
    from bot.helper.ext_utils.bulk_links import extract_bulk_links

    bulk = await extract_bulk_links(message, "0", "0")
    if len(bulk) > 1:
        await Encode(client, message).init_bulk(
            message.text.split("\n")[0].split(), 0, 0, Encode
        )
    else:
        bot_loop.create_task(Encode(client, message).new_event())
