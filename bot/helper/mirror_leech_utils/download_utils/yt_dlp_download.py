import builtins
import contextlib
from logging import getLogger
from os import listdir, path as ospath
from re import search as re_search

from yt_dlp import YoutubeDL

from bot import LOGGER, task_dict, task_dict_lock
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.ext_utils.task_manager import check_running_tasks, stop_duplicate_check
from bot.helper.mirror_leech_utils.status_utils.yt_dlp_status import YtDlpStatus
from bot.helper.telegram_helper.message_utils import send_message, send_status_message


class MyLogger:
    def __init__(self, obj, listener):
        self._obj = obj
        self._listener = listener

    def debug(self, msg):
        # Hack to fix changing extension
        if not self._obj.is_playlist and (
            match := re_search(r".Merger..Merging formats into..(.*?).$", msg)
            or re_search(r".ExtractAudio..Destination..(.*?)$", msg)
        ):
            LOGGER.info(msg)
            newname = match.group(1)
            newname = newname.split("/")[-1]
            self._listener.name = newname
            self._obj._ext = ospath.splitext(newname)[1]

    @staticmethod
    def warning(msg):
        LOGGER.warning(msg)

    @staticmethod
    def error(msg):
        if msg != "ERROR: Cancelling...":
            LOGGER.error(msg)


class YtDlpDownload:
    def __init__(self, listener):
        self._listener = listener
        self._downloaded_bytes = 0
        self._download_speed = 0
        self._eta = "-"
        self._progress = 0
        self._gid = ""
        self._ext = ""
        self.is_playlist = False
        self.keep_thumb = False
        self.opts = {
            "progress_hooks": [self._on_download_progress],
            "logger": MyLogger(self, self._listener),
            "usenetrc": True,
            "embedsubtitles": True,
            "prefer_ffmpeg": True,
            "nocheckcertificate": True,
            "postprocessors": [
                {
                    "key": "FFmpegEmbedSubtitle",
                }
            ],
            "cookiefile": "cookies.txt",
            "fragment_retries": 10,
            "retries": 10,
            "retry_sleep_functions": {
                "http": lambda _: 3,
                "fragment": lambda _: 3,
                "file_access": lambda _: 3,
                "extractor": lambda _: 3,
            },
        }

    def _on_download_progress(self, d):
        if d["status"] == "finished":
            if self.is_playlist:
                self._last_downloaded = 0
        elif d["status"] == "downloading":
            self._download_speed = d["speed"]
            if self.is_playlist:
                downloadedBytes = d["downloaded_bytes"]
                chunk_size = downloadedBytes - self._last_downloaded
                self._last_downloaded = downloadedBytes
                self._downloaded_bytes += chunk_size
            else:
                if d.get("total_bytes"):
                    self._listener.size = d["total_bytes"]
                elif d.get("total_bytes_estimate"):
                    self._listener.size = d["total_bytes_estimate"] or 0
                self._downloaded_bytes = d["downloaded_bytes"] or 0
                self._eta = d.get("eta", "-") or "-"
            with contextlib.suppress(builtins.BaseException):
                self._progress = (self._downloaded_bytes / self._listener.size) * 100

    async def _on_download_start(self, from_queue=False):
        async with task_dict_lock:
            task_dict[self._listener.mid] = YtDlpStatus(
                self._listener, self, self._gid
            )
        if not from_queue:
            await self._listener.on_download_start()
            if self._listener.multi <= 1 and not self._listener.is_rss:
                await send_status_message(self._listener.message)

    def _on_download_error(self, error):
        self._listener.is_cancelled = True
        async with task_dict_lock:
            if self._listener.mid in task_dict:
                del task_dict[self._listener.mid]
        LOGGER.error(f"{self._listener.name} | {error}")
        return

    def _extract_meta_data(self):
        if self._listener.link.startswith(("rtmp", "mms", "rstp", "rtmps")):
            self._listener.name = self._listener.link.split("/")[-1]
            self.opts["external_downloader"] = "ffmpeg"
        with YoutubeDL(self.opts) as ydl:
            try:
                result = ydl.extract_info(self._listener.link, download=False)
                if result is None:
                    raise ValueError("Info result is None")
            except Exception as e:
                return self._on_download_error(str(e))
            if "entries" in result:
                for entry in result["entries"]:
                    if not entry:
                        continue
                    self.is_playlist = True
                    break
                if self.is_playlist:
                    self._listener.size = 0
                    self._last_downloaded = 0
                    if not self._listener.name:
                        self._listener.name = result["title"]
                        if not self._listener.name:
                            self._listener.name = "Playlist"
                    return None
                if not self._listener.name:
                    outtmpl_ = "%(series,playlist_title,channel)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d.%(ext)s"
                    self._listener.name, ext = ospath.splitext(
                        ydl.prepare_filename(entry, outtmpl=outtmpl_)
                    )
                    if not self._ext:
                        self._ext = ext
            else:
                outtmpl_ = "%(title,fulltitle,alt_title)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d%(episode_number&E|)s%(episode_number|)02d%(height& |)s%(height|)s%(height&p|)s%(fps|)s%(fps&fps|)s%(tbr& |)s%(tbr|)d.%(ext)s"
                realName = ydl.prepare_filename(result, outtmpl=outtmpl_)
                ext = ospath.splitext(realName)[-1]
                self._listener.name = (
                    f"{self._listener.name}{ext}"
                    if self._listener.name
                    else realName
                )
                if not self._ext:
                    self._ext = ext
        return None

    def _download(self, path):
        try:
            with YoutubeDL(self.opts) as ydl:
                try:
                    ydl.download([self._listener.link])
                except Exception as e:
                    self._on_download_error(str(e))
                    return
            if self.is_playlist and (
                not ospath.exists(path) or len(listdir(path)) == 0
            ):
                self._on_download_error(
                    "No video available to download from this playlist. Check logs for more details"
                )
                return
            if self._listener.is_cancelled:
                return
            self._listener.on_download_complete()
        except Exception as e:
            self._on_download_error(str(e))

    async def add_download(self, path, qual, playlist, options):
        if "format" in options:
            self.opts["format"] = options["format"]
        else:
            self.opts["format"] = qual
        self.opts["postprocessors"] = [
            {
                "add_chapters": True,
                "add_infojson": "if_exists",
                "add_metadata": True,
                "key": "FFmpegMetadata",
            }
        ]

        if qual.startswith("ba/b-"):
            self._listener.name = f"{self._listener.name}.mp3"
            self._ext = ".mp3"
        elif "audio" in qual:
            self._listener.name = f"{self._listener.name}.mp3"
            self._ext = ".mp3"
            audio_format = "mp3"
            rate = "320"
            if "format" in options:
                audio_format = options.get("format", "mp3")
                rate = options.get("rate", "320")
            self.opts["postprocessors"].append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                    "preferredquality": rate,
                }
            )
            if audio_format == "vorbis":
                self._ext = ".ogg"
            elif audio_format == "m4a":
                self._ext = ".m4a"
            else:
                self._ext = f".{audio_format}"

        if not self._listener.is_leech or self._listener.thumbnail_layout:
            self.opts["writethumbnail"] = False

        if options:
            self._set_options(options)

        self._gid = self._listener.mid

        await self._on_download_start()

        self.opts["outtmpl"] = f"{path}/{self._listener.name}"

        if self._listener.name:
            self._listener.name = (
                self._listener.name.replace("/", "|")
                .replace("\\", "|")
                .replace(":", "|")
            )
            base_name = ospath.splitext(self._listener.name)[0]

        start_path = path if self.keep_thumb else f"{path}/yt-dlp-thumb"
        if self.is_playlist:
            self.opts["outtmpl"] = {
                "default": f"{path}/{self._listener.name}/%(title,fulltitle,alt_title)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d%(episode_number&E|)s%(episode_number|)02d%(height& |)s%(height|)s%(height&p|)s%(fps|)s%(fps&fps|)s%(tbr& |)s%(tbr|)d.%(ext)s",
                "thumbnail": f"{start_path}/%(title,fulltitle,alt_title)s%(season_number& |)s%(season_number&S|)s%(season_number|)02d%(episode_number&E|)s%(episode_number|)02d%(height& |)s%(height|)s%(height&p|)s%(fps|)s%(fps&fps|)s%(tbr& |)s%(tbr|)d.%(ext)s",
            }
        elif "download_ranges" in options:
            self.opts["outtmpl"] = {
                "default": f"{path}/{base_name}/%(section_number|)s%(section_number&.|)s%(section_title|)s%(section_title&-|)s%(title,fulltitle,alt_title)s %(section_start)s to %(section_end)s.%(ext)s",
                "thumbnail": f"{start_path}/%(section_number|)s%(section_number&.|)s%(section_title|)s%(section_title&-|)s%(title,fulltitle,alt_title)s %(section_start)s to %(section_end)s.%(ext)s",
            }
        elif any(
            key in options
            for key in [
                "writedescription",
                "writeinfojson",
                "writeannotations",
                "writedesktoplink",
                "writewebloclink",
                "writelink",
                "writeurllink",
                "writesubtitles",
                "write_all_thumbnails",
            ]
        ):
            self.opts["outtmpl"] = {
                "default": f"{path}/{base_name}/{self._listener.name}",
                "thumbnail": f"{start_path}/{base_name}.%(ext)s",
            }
        else:
            self.opts["outtmpl"] = {
                "default": f"{path}/{self._listener.name}",
                "thumbnail": f"{start_path}/{base_name}.%(ext)s",
            }

        if qual.startswith("ba/b"):
            self._listener.name = f"{base_name}{self._ext}"

        if self.opts["writethumbnail"]:
            self.opts["postprocessors"].append(
                {
                    "format": "jpg",
                    "key": "FFmpegThumbnailsConvertor",
                    "when": "before_dl",
                }
            )
        if self._ext in [
            ".mp3",
            ".mkv",
            ".m4a",
            ".flac",
            ".opus",
            ".ogg",
            ".webm",
        ]:
            self.opts["postprocessors"].append(
                {
                    "already_have_thumbnail": self.opts["writethumbnail"],
                    "key": "EmbedThumbnail",
                }
            )

        msg, button = await stop_duplicate_check(self._listener)
        if msg:
            await send_message(self._listener.message, msg, button)
            return

        self._extract_meta_data()
        if self._listener.is_cancelled:
            return

        if not self.is_playlist:
            check, _, _, _ = await check_running_tasks(self._listener)
            if check:
                return

        if not self._listener.is_cancelled:
            LOGGER.info(f"Added to Queue/Download: {self._listener.name}")
            async with task_dict_lock:
                task_dict[self._listener.mid] = QueueStatus(
                    self._listener, self._gid, "dl"
                )
            await event.wait()
            if self._listener.is_cancelled:
                return

        if not self._listener.is_cancelled:
            await self._on_download_start(True)
            await sync_to_async(self._download, path)

    def _set_options(self, options):
        for key, value in options.items():
            if key in ["postprocessors", "progress_hooks"]:
                if isinstance(value, list):
                    self.opts[key].extend(value)
            elif key == "download_ranges":
                if isinstance(value, list):
                    self.opts[key] = lambda _, __, value=value: value
            else:
                if key == "writethumbnail" and value is True:
                    self.keep_thumb = True
                self.opts[key] = value
