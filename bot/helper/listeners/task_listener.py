from asyncio import sleep
from html import escape
from re import search as re_search

from aiofiles.os import listdir, path as aiopath
from aioshutil import rmtree

from bot import (
    DOWNLOAD_DIR,
    LOGGER,
    Config,
    non_queued_dl,
    queue_dict_lock,
    task_dict,
    task_dict_lock,
)
from bot.helper.common import TaskConfig
from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.ext_utils.files_utils import (
    get_path_size,
    join_files,
    remove_excluded_files,
    remove_non_included_files,
)
from bot.helper.ext_utils.links_utils import is_gdrive_id
from bot.helper.ext_utils.status_utils import get_readable_file_size, get_readable_time
from bot.helper.ext_utils.task_manager import check_running_tasks, start_from_queued
from bot.helper.mirror_leech_utils.gdrive_utils.upload import GoogleDriveUpload
from bot.helper.mirror_leech_utils.gofile_utils.upload import GoFileUpload
from bot.helper.mirror_leech_utils.rclone_utils.transfer import RcloneTransferHelper
from bot.helper.mirror_leech_utils.status_utils.gdrive_status import (
    GoogleDriveStatus,
)
from bot.helper.mirror_leech_utils.status_utils.gofile_status import GoFileStatus
from bot.helper.mirror_leech_utils.status_utils.queue_status import QueueStatus
from bot.helper.mirror_leech_utils.status_utils.rclone_status import RcloneStatus
from bot.helper.mirror_leech_utils.status_utils.telegram_status import TelegramStatus
from bot.helper.mirror_leech_utils.telegram_uploader import TelegramUploader
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import (
    delete_message,
    send_message,
)
from time import time


class TaskListener(TaskConfig):
    def __init__(self):
        super().__init__()

    async def clean(self):
        try:
            if await aiopath.exists(self.dir):
                await rmtree(self.dir, ignore_errors=True)
        except Exception:
            pass

    async def on_download_start(self):
        if (
            Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
            and self.user_id != Config.OWNER_ID
        ):
            await database.add_incomplete_task(
                self.message.chat.id,
                self.message.link,
                self.tag,
            )

    async def on_download_complete(self):
        await sleep(2)
        if self.is_cancelled:
            return
        if self.is_task_empty():
            await self.on_upload_error("No files to upload!")
            return
        if not self.is_torrent and self.is_qbit:
            self.name, self.size = await self.get_content_details(self.dir)
        if self.is_playlist and self.is_ytdlp:
            self.name, self.size = await self.get_content_details(self.dir)
        if not self.is_ytdlp and not self.is_qbit:
            self.name, self.size = await self.get_content_details(self.dir)

        if self.join and await aiopath.isdir(self.dir):
            await join_files(self.dir)

        if self.extract:
            self.dir = await self.proceed_extract(self.dir, self.mid)
            if self.is_cancelled:
                return

        if self.ffmpeg_cmds:
            self.dir = await self.proceed_ffmpeg(self.dir, self.mid)
            if self.is_cancelled:
                return

        up_path = f"{self.dir}/{self.name}" if self.is_file else self.dir
        if not await aiopath.exists(up_path):
            try:
                files = await listdir(self.dir)
                self.name = files[0]
                if self.name == "yt-dlp-thumb":
                    self.name = files[1]
                up_path = f"{self.dir}/{self.name}"
            except Exception:
                await self.on_upload_error(
                    "Download Complete! but the file/folder not found. Check logs for more details!",
                )
                return

        if self.is_leech and not self.compress and not self.is_file:
            self.is_file = await aiopath.isfile(up_path)

        if self.screen_shots:
            up_path = await self.generate_screenshots(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{self.dir}/", "").split("/", 1)[0]

        if self.convert_audio or self.convert_video:
            up_path = await self.convert_media(up_path, self.mid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{self.dir}/", "").split("/", 1)[0]

        if self.sample_video:
            up_path = await self.generate_sample_video(up_path, self.mid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{self.dir}/", "").split("/", 1)[0]

        if self.metadata:
            up_path = await self.proceed_metadata(up_path, self.mid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{self.dir}/", "").split("/", 1)[0]

        if self.e_thumb:
            up_path = await self.proceed_embed_thumb(up_path, self.mid)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{self.dir}/", "").split("/", 1)[0]

        if not self.included_extensions:
            await remove_excluded_files(
                self.up_dir or self.dir, self.excluded_extensions
            )
        else:
            await remove_non_included_files(
                self.up_dir or self.dir, self.included_extensions
            )
        if not Config.QUEUE_ALL:
            async with queue_dict_lock:
                if self.mid in non_queued_dl:
                    non_queued_dl.remove(self.mid)
            await start_from_queued()

        if self.compress:
            up_path = await self.proceed_compress(up_path, self.mid)
            if self.is_cancelled:
                return
            self.is_file = True  # After compress it is a file
            up_dir = self.dir
            self.name = up_path.replace(f"{up_dir}/", "").split("/", 1)[0]
            self.size = await get_path_size(up_dir)
            self.clear()
            if not self.included_extensions:
                await remove_excluded_files(up_dir, self.excluded_extensions)
            else:
                await remove_non_included_files(up_dir, self.included_extensions)

        if self.watermark:
            up_path = await self.proceed_watermark(
                up_path,
                self.mid,
            )
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{self.dir}/", "").split("/", 1)[0]

        if self.is_leech and self.split_size:
            self.size = await get_path_size(up_path)
            if self.size > self.split_size:
                await self.proceed_split(up_path, self.mid)
                if self.is_cancelled:
                    return
            self.clear()

        if self.name_prefix:
            up_path = await self.proceed_name_prefix(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{self.dir}/", "").split("/", 1)[0]

        up_path = await self.remove_www_prefix(up_path)
        self.is_file = await aiopath.isfile(up_path)
        self.name = up_path.replace(f"{self.dir}/", "").split("/", 1)[0]

        if self.name_sub:
            LOGGER.info(f"Start Name Substitution {up_path}")
            up_path = await self.substitute(up_path)
            if self.is_cancelled:
                return
            self.is_file = await aiopath.isfile(up_path)
            self.name = up_path.replace(f"{self.dir}/", "").split("/", 1)[0]

        self.size = await get_path_size(up_path)
        if self.is_leech:
            LOGGER.info(f"Leech Name: {self.name}")
            tg = TelegramUploader(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = TelegramStatus(self, tg, self.mid, "up")
            await gather(
                tg.upload(),
                self.cancel_task(),
            )  # TODO: Investigate why we need to call cancel_task
        elif self.up_dest == "rc":
            LOGGER.info(f"Rclone Upload Name: {self.name}")
            rc = RcloneTransferHelper(self)
            async with task_dict_lock:
                task_dict[self.mid] = RcloneStatus(self, rc, self.mid, "up")
            await rc.upload(up_path)
        elif self.up_dest == "gd":
            LOGGER.info(f"Gdrive Upload Name: {self.name}")
            gd = GoogleDriveUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = GoogleDriveStatus(self, gd, self.mid, "up")
            await gd.upload()
        elif self.up_dest == "yt":
            LOGGER.info(f"YouTube Upload Name: {self.name}")
            from bot.helper.mirror_leech_utils.download_utils.yt_dlp_download import (
                YtDlpDownload,
            )
            from bot.helper.mirror_leech_utils.status_utils.yt_dlp_status import (
                YtDlpStatus,
            )

            yt = YtDlpDownload(self)
            async with task_dict_lock:
                task_dict[self.mid] = YtDlpStatus(self, yt, self.mid, "up")
            await yt.upload(up_path)
            del yt
        elif self.up_dest == "gofile":
            LOGGER.info(f"GoFile Upload Name: {self.name}")
            gofile = GoFileUpload(self, up_path)
            async with task_dict_lock:
                task_dict[self.mid] = GoFileStatus(self, gofile, self.mid, "up")
            await gofile.upload()

    async def on_upload_complete(
        self,
        link,
        files,
        folders,
        mime_type,
        dir_id,
        user_id=None,
    ):
        if (
            Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
            and self.user_id != Config.OWNER_ID
        ):
            await database.rm_complete_task(self.message.link)
        msg = f"<b>Name:</b> <code>{escape(self.name)}</code>\n\n"
        msg += f"<b>Size:</b> {get_readable_file_size(self.size)}\n"
        msg += f"<b>Elapsed:</b> {get_readable_time(time() - self.start_time)}\n"
        if self.is_leech:
            msg += f"<b>Total Files:</b> {folders}\n"
            if mime_type != 0:
                msg += f"<b>Corrupted Files:</b> {mime_type}\n"
            msg += f"<b>Uploaded By:</b> {self.tag}\n\n"
            if not files:
                await send_message(self.message, msg)
            else:
                fmsg = ""
                for index, (link, name) in enumerate(files.items(), start=1):
                    fmsg += f"{index}. <a href='{link}'>{escape(name)}</a>\n"
                    if len(fmsg.encode() + msg.encode()) > 4000:
                        await send_message(self.message, msg + fmsg)
                        fmsg = ""
                if fmsg:
                    await send_message(self.message, msg + fmsg)
        else:
            msg += f"<b>Type:</b> {mime_type}\n"
            if mime_type == "Folder":
                msg += f"<b>SubFolders:</b> {folders}\n"
                msg += f"<b>Files:</b> {files}\n"
            if link or dir_id:
                buttons = ButtonMaker()
                if link:
                    buttons.url_button("☁️ Cloud Link", link)
                if dir_id:
                    INDEX_URL = ""
                    if self.private_link:
                        INDEX_URL = (
                            self.user_dict.get("INDEX_URL", "") or Config.INDEX_URL
                        )
                    elif Config.INDEX_URL:
                        INDEX_URL = Config.INDEX_URL
                    if INDEX_URL:
                        share_url = f"{INDEX_URL}findpath?id={dir_id}"
                        buttons.url_button("Index Link", share_url)
                        if mime_type.startswith(("image", "video", "audio")):
                            share_urls = f"{INDEX_URL}findpath?id={dir_id}&view=true"
                            buttons.url_button("🌐 View Link", share_urls)
                button = buttons.build_menu(2)
            else:
                button = None
            msg += f"<b>Uploaded By:</b> {self.tag}\n\n"
            if self.seed:
                if self.is_qbit:
                    if self.is_leech:
                        await send_message(self.message, msg, button)
                    return
                msg += f"<b>Seeders:</b> {self.seeders} | <b>Leechers:</b> {self.leechers}\n"
            await send_message(self.message, msg, button)
        if self.is_super_chat:
            if Config.DELETE_LINKS:
                await delete_message(self.message)
            if self.user_id != self.message.from_user.id:
                await delete_message(self.message.reply_to_message)
        await self.clean()

    async def on_download_error(self, error):
        await self.clean()
        if (
            Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
            and self.user_id != Config.OWNER_ID
        ):
            await database.rm_complete_task(self.message.link)
        await send_message(self.message, f"Error: {error}")
        if not Config.QUEUE_ALL:
            async with queue_dict_lock:
                if self.mid in non_queued_dl:
                    non_queued_dl.remove(self.mid)
            await start_from_queued()

    async def on_upload_error(self, error):
        await self.clean()
        if (
            Config.INCOMPLETE_TASK_NOTIFIER
            and Config.DATABASE_URL
            and self.user_id != Config.OWNER_ID
        ):
            await database.rm_complete_task(self.message.link)
        await send_message(self.message, f"Error: {error}")
        if not Config.QUEUE_ALL:
            async with queue_dict_lock:
                if self.mid in non_queued_up:
                    non_queued_up.remove(self.mid)
            await start_from_queued()

    def is_task_empty(self):
        # Implementation to check if task is empty
        # Placeholder for brevity
        return False

    async def get_content_details(self, path):
        # Placeholder
        return self.name, 0
