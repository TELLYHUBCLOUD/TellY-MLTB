import json
from asyncio import Event, create_task, wait_for
from functools import partial
from os import makedirs, walk
from os import path as ospath
from re import search as re_search
from time import time

from aiofiles import open as aiopen
from aiofiles.os import listdir, remove
from aiofiles.os import path as aiopath
from aioshutil import move

from bot import DOWNLOAD_DIR, LOGGER, bot_loop, task_dict, task_dict_lock
from bot.core.aeon_client import TgClient
from bot.helper.aeon_utils.access_check import error_check
from bot.helper.ext_utils.bot_utils import (
    arg_parser,
    cmd_exec,
    new_task,
    sync_to_async,
)
from bot.helper.ext_utils.links_utils import is_telegram_link, is_url
from bot.helper.ext_utils.media_utils import (
    FFMpeg,
    get_path_size,
    get_remote_media_info,
    get_streams,
)
from bot.helper.ext_utils.status_utils import get_readable_time
from bot.helper.listeners.task_listener import TaskListener
from bot.helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from bot.helper.mirror_leech_utils.status_utils.ffmpeg_status import FFmpegStatus
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
    elif data[1] == "qual":
        obj.quality = data[2]
        await obj.main_menu()
    elif data[1] == "toggle_audio":
        index = int(data[2])
        if obj.streams:
            obj.audio_map[index] = not obj.audio_map[index]
        else:
            obj.remove_audio = not obj.remove_audio
        await obj.main_menu()
    elif data[1] == "toggle_sub":
        index = int(data[2])
        if obj.streams:
            obj.sub_map[index] = not obj.sub_map[index]
        else:
            obj.remove_subs = not obj.remove_subs
        await obj.main_menu()
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
        self.quality = "Original"
        self.audio_map = {}
        self.sub_map = {}
        self.remove_audio = False
        self.remove_subs = False
        self.is_cancelled = False
        self.event = Event()
        self._reply_to = None
        self._timeout = 60
        self._start_time = time()

        if streams:
            for stream in streams:
                if stream["codec_type"] == "audio":
                    self.audio_map[stream["index"]] = True
                elif stream["codec_type"] == "subtitle":
                    self.sub_map[stream["index"]] = True

    @property
    def is_timed_out(self):
        return (time() - self._start_time) > self._timeout

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
            return None, None, None

        if self.streams:
            return self.quality, self.audio_map, self.sub_map
        return self.quality, self.remove_audio, self.remove_subs

    async def main_menu(self):
        buttons = ButtonMaker()
        buttons.data_button(f"Compress: {self.quality}", "enc compress")

        if self.streams:
            for stream in self.streams:
                if stream["codec_type"] == "audio":
                    idx = stream["index"]
                    lang = stream.get("tags", {}).get("language", "und")
                    title = stream.get("tags", {}).get("title", "")
                    label = f"{lang} ({stream.get('codec_name', 'unk')})"
                    if title:
                        label += f" - {title}"

                    icon = "✅" if self.audio_map.get(idx, True) else "❌"
                    buttons.data_button(
                        f"{icon} Audio: {label}", f"enc toggle_audio {idx}"
                    )

            for stream in self.streams:
                if stream["codec_type"] == "subtitle":
                    idx = stream["index"]
                    lang = stream.get("tags", {}).get("language", "und")
                    title = stream.get("tags", {}).get("title", "")
                    label = f"{lang} ({stream.get('codec_name', 'unk')})"
                    if title:
                        label += f" - {title}"

                    icon = "✅" if self.sub_map.get(idx, True) else "❌"
                    buttons.data_button(
                        f"{icon} Sub: {label}", f"enc toggle_sub {idx}"
                    )
        else:
            a_icon = "❌" if self.remove_audio else "✅"
            buttons.data_button(f"{a_icon} Audio (All)", "enc toggle_audio 0")

            s_icon = "❌" if self.remove_subs else "✅"
            buttons.data_button(f"{s_icon} Subs (All)", "enc toggle_sub 0")

        buttons.data_button("Done", "enc done")
        buttons.data_button("Cancel", "enc cancel")

        msg_text = (
            f"<b>Encode Settings</b>\n"
            f"Timeout: {get_readable_time(self._timeout - (time() - self._start_time))}\n"
        )

        markup = buttons.build_menu(1)

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

        buttons.data_button("Back", "enc done")
        markup = buttons.build_menu(2)
        await edit_message(self._reply_to, "Select Quality", markup)


class Encode(TaskListener):
    def __init__(self, client, message, **kwargs):
        self.message = message
        self.client = client
        self.quality = ""
        self.remove_audio = False
        self.remove_subs = False
        self.audio_map = {}
        self.sub_map = {}
        self.has_metadata_selection = False
        super().__init__()
        self.is_leech = True
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

        LOGGER.info(f"Video Tool Request: Link: {self.link}")

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
                            await aioremove(des_path)

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

        qual, map1, map2 = await selector.get_selection()
        if qual is None:
            return None

        self.quality = qual
        if streams:
            self.audio_map = map1
            self.sub_map = map2
        else:
            self.remove_audio = map1
            self.remove_subs = map2

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
                if file_name.endswith((".aria2", ".!qB")):
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
        ffmpeg = FFMpeg(self)
        async with task_dict_lock:
            if self.mid in task_dict:
                self.gid = task_dict[self.mid].gid()
            task_dict[self.mid] = FFmpegStatus(self, ffmpeg, self.gid, "encoding")

        await send_status_message(self.message)

        cmd = [
            "xtra",
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            file_path,
        ]

        local_streams = []
        if self.has_metadata_selection:
            try:
                result = await cmd_exec(
                    [
                        "ffprobe",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-print_format",
                        "json",
                        "-show_streams",
                        file_path,
                    ]
                )
                if result[0]:
                    local_streams = json.loads(result[0]).get("streams", [])
            except:
                pass

        if self.has_metadata_selection and local_streams:
            for stream in local_streams:
                idx = stream["index"]
                ctype = stream["codec_type"]
                if ctype == "video":
                    cmd.extend(["-map", f"0:{idx}"])
                elif ctype == "audio":
                    if self.audio_map.get(idx, True):
                        cmd.extend(["-map", f"0:{idx}"])
                elif ctype == "subtitle":
                    if self.sub_map.get(idx, True):
                        cmd.extend(["-map", f"0:{idx}"])
                else:
                    cmd.extend(["-map", f"0:{idx}"])
        else:
            if self.remove_audio:
                cmd.append("-an")
            else:
                cmd.extend(["-c:a", "copy"])
            if self.remove_subs:
                cmd.append("-sn")
            else:
                cmd.extend(["-c:s", "copy"])

        if self.quality != "Original":
            cmd.extend(["-c:v", "libx264"])
            scale = ""
            if self.quality == "1080p":
                scale = "scale=-2:1080"
            elif self.quality == "720p":
                scale = "scale=-2:720"
            elif self.quality == "576p":
                scale = "scale=-2:576"
            elif self.quality == "480p":
                scale = "scale=-2:480"
            elif self.quality == "360p":
                scale = "scale=-2:360"
            elif self.quality == "240p":
                scale = "scale=-2:240"
            elif self.quality == "144p":
                scale = "scale=-2:144"
            if scale:
                cmd.extend(["-vf", scale])
        else:
            cmd.extend(["-c:v", "copy"])

        if self.has_metadata_selection:
            cmd.extend(["-c:a", "copy", "-c:s", "copy"])

        output_file = (
            f"{ospath.splitext(file_path)[0]}_encoded{ospath.splitext(file_path)[1]}"
        )
        cmd.append(output_file)

        res = await ffmpeg.metadata_watermark_cmds(cmd, file_path)
        if res:
            try:
                if await aiopath.exists(file_path):
                    await remove(file_path)
                for f in await listdir(self.dir):
                    if f.endswith((".aria2", ".!qB")):
                        await remove(f"{self.dir}/{f}")
                if await aiopath.exists(output_file):
                    self.name = ospath.basename(output_file)
                    new_path = f"{self.dir}/{self.name}"
                    if ospath.dirname(output_file) != self.dir:
                        await move(output_file, new_path)
                else:
                    await self.on_upload_error("Encoded file not found!")
                    return
            except Exception as e:
                LOGGER.error(f"Error Cleanup: {e}")
            await super().on_download_complete()
        else:
            await self.on_upload_error("Encoding Failed.")


async def videotool(client, message):
    from bot.helper.ext_utils.bulk_links import extract_bulk_links

    bulk = await extract_bulk_links(message, "0", "0")
    if len(bulk) > 1:
        await Encode(client, message).init_bulk(
            message.text.split("\n")[0].split(), 0, 0, Encode
        )
    else:
        bot_loop.create_task(Encode(client, message).new_event())
