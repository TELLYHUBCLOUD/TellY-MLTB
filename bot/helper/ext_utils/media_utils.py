from asyncio import create_subprocess_exec, gather, wait_for
from asyncio.subprocess import PIPE
from os import path as ospath
from re import escape
from time import time

from aiofiles.os import makedirs
from aioshutil import rmtree

from bot import DOWNLOAD_DIR, LOGGER, threads

from .bot_utils import cmd_exec, sync_to_async
from .files_utils import get_mime_type, is_archive_split


async def create_thumb(msg, _=None):
    if not msg:
        return ""
    file_handler = msg.photo or msg.document
    if not file_handler:
        return ""
    if (
        msg.document
        and not msg.document.mime_type.startswith("image")
        and not msg.document.mime_type.startswith("video")
    ):
        return ""
    if msg.photo:
        if not msg.photo.file_size:
            return ""
    elif msg.document and not msg.document.file_size:
        return ""
    des_dir = f"{DOWNLOAD_DIR}thumbnails/"
    await makedirs(des_dir, exist_ok=True)
    ext = ".jpg" if msg.photo else ospath.splitext(msg.document.file_name)[1]
    path = f"{des_dir}{time()}{ext}"
    await msg.download(file_name=path)
    return path


async def is_multi_streams(path):
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-show_streams",
                "-print_format",
                "json",
                path,
            ]
        )
        if result[1] and result[2] != 0:
            return False
    except Exception:
        return False
    fields = eval(result[0]).get("streams")
    if fields is None:
        LOGGER.error(f"get_media_info: {result}")
        return False
    videos = 0
    audios = 0
    for stream in fields:
        if stream.get("codec_type") == "video":
            videos += 1
        elif stream.get("codec_type") == "audio":
            audios += 1
    return videos > 1 or audios > 1


async def get_media_info(path, return_all=False):
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-show_streams",
                "-print_format",
                "json",
                path,
            ]
        )
        if result[1] and result[2] != 0:
            return (0, "", "", "") if return_all else (0, None, None)
    except Exception:
        return (0, "", "", "") if return_all else (0, None, None)
    fields = eval(result[0]).get("streams")
    if fields is None:
        LOGGER.error(f"get_media_info: {result}")
        return (0, "", "", "") if return_all else (0, None, None)
    duration = 0
    lang = ""
    quality = ""
    artist = ""
    title = ""
    for stream in fields:
        if stream.get("codec_type") == "video":
            duration = int(float(stream.get("duration", 0)))
            if not quality:
                quality = stream.get("height")
        elif stream.get("codec_type") == "audio":
            if not lang:
                lang = stream.get("tags", {}).get("language")
            if not artist:
                artist = stream.get("tags", {}).get("artist")
            if not title:
                title = stream.get("tags", {}).get("title")
    if return_all:
        return duration, quality, lang, title
    return duration, artist, title


async def get_document_type(path):
    is_video, is_audio, is_image = False, False, False
    if path.endswith(tuple(is_archive_split)):
        return is_video, is_audio, is_image
    mime_type = get_mime_type(path)
    if mime_type.startswith("image"):
        is_image = True
        return is_video, is_audio, is_image
    if mime_type.startswith("audio"):
        is_audio = True
        return is_video, is_audio, is_image
    if not mime_type.startswith("video") and not mime_type.endswith("octet-stream"):
        return is_video, is_audio, is_image
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-show_streams",
                "-print_format",
                "json",
                path,
            ]
        )
        if result[1] and result[2] != 0:
            return is_video, is_audio, is_image
    except Exception:
        return is_video, is_audio, is_image
    fields = eval(result[0]).get("streams")
    if fields is None:
        LOGGER.error(f"get_document_type: {result}")
        return is_video, is_audio, is_image
    for stream in fields:
        if stream.get("codec_type") == "video":
            is_video = True
        elif stream.get("codec_type") == "audio":
            is_audio = True
    return is_video, is_audio, is_image


async def take_ss(video_file, ss_nb) -> bool:
    duration = (await get_media_info(video_file))[0]
    if duration != 0:
        dirpath = ospath.join(
            ospath.dirname(video_file),
            f"{ospath.splitext(ospath.basename(video_file))[0]}_ss",
        )
        await makedirs(dirpath, exist_ok=True)
        interval = duration // (ss_nb + 1)
        cap_time = interval
        name = escape(ospath.basename(video_file))
        cmds = []
        try:
            for i in range(ss_nb):
                output = f"{dirpath}/SS.{name}_{i:02}.png"
                cmd = [
                    "xtra",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{cap_time}",
                    "-i",
                    video_file,
                    "-vframes",
                    "1",
                    "-frames:v",
                    "1",
                    "-threads",
                    f"{threads}",
                    output,
                ]
                cap_time += interval
                cmds.append(create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE))
            resutls = await wait_for(gather(*cmds), timeout=60)
            if resutls[0][2] != 0:
                LOGGER.error(
                    f"Error while creating screenshots from video. Path: {video_file}. stderr: {resutls[0][1]}",
                )
                await rmtree(dirpath, ignore_errors=True)
                return False
        except Exception:
            LOGGER.error(
                f"Error while creating screenshots from video. Path: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!",
            )
            await rmtree(dirpath, ignore_errors=True)
            return False
        return dirpath
    LOGGER.error("take_ss: Can't get the duration of video")
    return False


async def get_audio_thumbnail(audio_file):
    output_dir = f"{DOWNLOAD_DIR}thumbnails/"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "xtra",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        audio_file,
        "-an",
        "-vcodec",
        "copy",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        await cmd_exec(cmd)
        if await sync_to_async(ospath.exists, output):
            return output
    except Exception as e:
        LOGGER.error(f"get_audio_thumbnail: {e}")
    return "none"


async def get_video_thumbnail(video_file, duration):
    output_dir = f"{DOWNLOAD_DIR}thumbnails/"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration // 2
    cmd = [
        "xtra",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{duration}",
        "-i",
        video_file,
        "-vframes",
        "1",
        "-frames:v",
        "1",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        await cmd_exec(cmd)
        if await sync_to_async(ospath.exists, output):
            return output
    except Exception as e:
        LOGGER.error(f"get_video_thumbnail: {e}")
    return "none"


async def get_multiple_frames_thumbnail(video_file, layout, keep_screenshots):
    output_dir = f"{DOWNLOAD_DIR}thumbnails/"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "xtra",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        video_file,
        "-vf",
        f"thumbnail,tile={layout}",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        await cmd_exec(cmd)
        if await sync_to_async(ospath.exists, output):
            return output
    except Exception as e:
        LOGGER.error(f"get_multiple_frames_thumbnail: {e}")
    return "none"


class FFMpeg:
    def __init__(self, listener):
        self._listener = listener
        self._progress_raw = 0
        self._eta_raw = 0
        self._processed_bytes = 0
        self._subsize = listener.subsize

    @property
    def speed_raw(self):
        try:
            return self._processed_bytes / (time() - self._listener.start_time)
        except ZeroDivisionError:
            return 0

    @property
    def progress_raw(self):
        return self._progress_raw

    @property
    def eta_raw(self):
        return self._eta_raw

    @property
    def processed_bytes(self):
        return self._processed_bytes

    def clear(self):
        self._progress_raw = 0
        self._eta_raw = 0
        self._processed_bytes = 0

    async def _ffmpeg_progress(self):
        while not (
            self._listener.subproc.returncode is not None
            or self._listener.is_cancelled
        ):
            try:
                line = await wait_for(self._listener.subproc.stdout.readline(), 5)
            except Exception:
                break
            if not line:
                break
            line = line.decode().strip()
            if not self._listener.progress:
                continue
            progress = {}
            if line.startswith("out_time_ms") and "N/A" not in line:
                progress["time"] = int(line.split("=")[1]) / 1000000
            elif line.startswith("total_size"):
                progress["size"] = int(line.split("=")[1])
            if "time" in progress:
                self._processed_bytes = progress["size"]
                self._progress_raw = (self._processed_bytes / self._subsize) * 100
                try:
                    self._eta_raw = (
                        self._subsize - self._processed_bytes
                    ) / self.speed_raw
                except Exception:
                    self._progress_raw = 0
                    self._eta_raw = 0

    async def ffmpeg_cmds(self, ffmpeg, f_path):
        self.clear()
        self._listener.subproc = await create_subprocess_exec(
            *ffmpeg,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._ffmpeg_progress()
        returncode = await self._listener.subproc.wait()
        if returncode == 0:
            return (
                await listdir(ffmpeg[-1])
                if await sync_to_async(ospath.isdir, ffmpeg[-1])
                else [ffmpeg[-1]]
            )
        return False

    async def metadata_watermark_cmds(self, ffmpeg, f_path):
        self.clear()
        self._listener.subproc = await create_subprocess_exec(
            *ffmpeg,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._ffmpeg_progress()
        returncode = await self._listener.subproc.wait()
        return returncode == 0

    async def convert_video(self, video_file, ext, retry=False):
        base_name = ospath.splitext(video_file)[0]
        output = f"{base_name}.{ext}"
        if retry:
            cmd = [
                "xtra",
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-threads",
                f"{threads}",
                output,
            ]
            if ext == "mp4":
                cmd[17:17] = ["-c:s", "mov_text"]
            elif ext == "mkv":
                cmd[17:17] = ["-c:s", "ass"]
            else:
                cmd[17:17] = ["-c:s", "copy"]
        else:
            cmd = [
                "xtra",
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                output,
            ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._ffmpeg_progress()
        returncode = await self._listener.subproc.wait()
        if returncode == 0:
            return output
        if not retry:
            return await self.convert_video(video_file, ext, True)
        return False

    async def convert_audio(self, audio_file, ext):
        base_name = ospath.splitext(audio_file)[0]
        output = f"{base_name}.{ext}"
        cmd = [
            "xtra",
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            audio_file,
            "-threads",
            f"{threads}",
            output,
        ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._ffmpeg_progress()
        returncode = await self._listener.subproc.wait()
        if returncode == 0:
            return output
        return False

    async def sample_video(self, video_file, sample_duration, part_duration):
        output_file = f"{ospath.splitext(video_file)[0]}_sample.{ospath.splitext(video_file)[1]}"
        segments = []
        duration = (await get_media_info(video_file))[0]
        if duration == 0:
            return False
        total_parts = sample_duration // part_duration
        interval = duration // (total_parts + 1)

        filter_complex = ""
        for i in range(total_parts):
            start_time = (i + 1) * interval
            segments.append(
                f"[0:v]trim=start={start_time}:duration={part_duration},setpts=PTS-STARTPTS[v{i}];"
            )
            segments.append(
                f"[0:a]atrim=start={start_time}:duration={part_duration},asetpts=PTS-STARTPTS[a{i}];"
            )
            filter_complex += f"[v{i}][a{i}]"

        filter_complex = "".join(segments) + filter_complex
        filter_complex += f"concat=n={len(segments)}:v=1:a=1[vout][aout]"

        cmd = [
            "xtra",
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            video_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-threads",
            f"{threads}",
            output_file,
        ]

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._ffmpeg_progress()
        returncode = await self._listener.subproc.wait()
        if returncode == 0:
            return output_file
        return False

    async def split(self, f_path, file_, parts, split_size):
        duration = (await get_media_info(f_path))[0]
        if duration == 0:
            return False
        multi_streams = await is_multi_streams(f_path)
        i = 1
        start_time = 0
        extension = ospath.splitext(file_)[1]
        base_name = ospath.splitext(file_)[0]
        while i <= parts or start_time < duration - 4:
            out_path = f_path.replace(file_, f"{base_name}.part{i:03}{extension}")
            cmd = [
                "xtra",
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-ss",
                str(start_time),
                "-i",
                f_path,
                "-fs",
                str(split_size),
                "-map",
                "0",
                "-map_metadata",
                "0",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                out_path,
            ]
            if not multi_streams:
                del cmd[15]
                del cmd[15]
            if self._listener.is_cancelled:
                return False
            self._listener.subproc = await create_subprocess_exec(
                *cmd,
                stdout=PIPE,
                stderr=PIPE,
            )
            await self._ffmpeg_progress()
            returncode = await self._listener.subproc.wait()
            if returncode == -9:
                self._listener.is_cancelled = True
                return False
            if returncode != 0:
                return False
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f"Something went wrong while splitting the file: {f_path}"
                )
                break
            start_time += lpd - 3
            i += 1
            if duration == lpd:
                LOGGER.warning(
                    f"This file has been splitted with default stream and audio, so you will only see one part with less size from original one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {f_path}",
                )
                break
            if lpd <= 3:
                break
        return True

    async def merge(self, file_path, merge_paths, metadata_key=""):
        output = f"{file_path}.merged.mkv"
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

        input_count = 1
        for path in merge_paths:
            cmd.extend(["-i", path])
            input_count += 1

        cmd.extend(
            [
                "-c",
                "copy",
                "-map",
                "0",
            ]
        )

        for i in range(1, input_count):
            cmd.extend(["-map", f"{i}"])

        if metadata_key:
            cmd.extend(["-metadata", f"title={metadata_key}"])

        cmd.extend(
            [
                "-threads",
                f"{threads}",
                output,
            ]
        )

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._ffmpeg_progress()
        returncode = await self._listener.subproc.wait()
        if returncode == 0:
            return output
        return False
