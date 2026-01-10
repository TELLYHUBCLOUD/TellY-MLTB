from asyncio import Event, wait_for
from time import time
from functools import partial
from pyrogram.filters import regex, user
from pyrogram.handlers import CallbackQueryHandler

from bot import LOGGER, task_dict, task_dict_lock
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
    auto_delete_message,
)
from bot.helper.ext_utils.status_utils import get_readable_time

# Store interactive session results globally to bridge between modules
# key: user_id, value: bool (Proceed or Cancel)
direct_task_results = {}

# ... (Previous imports)
from asyncio import create_task, sleep
from base64 import b64encode
from re import match as re_match

from aiofiles.os import path as aiopath
from truelink import TrueLinkResolver
from truelink.exceptions import TrueLinkException
from truelink.types import FolderResult, LinkResult

from bot import (
    DOWNLOAD_DIR,
    LOGGER,
    included_extensions,
    multi_tags,
    task_dict,
    task_dict_lock,
    user_data,
    bot_loop
)
from bot.core.config_manager import Config
from bot.core.telegram_manager import TgClient
from bot.helper.aeon_utils.access_check import error_check
from bot.helper.ext_utils.bot_utils import (
    COMMAND_USAGE,
    arg_parser,
    get_content_type,
    new_task,
)
from bot.helper.ext_utils.links_utils import (
    get_links_from_message,
    is_gdrive_id,
    is_gdrive_link,
    is_magnet,
    is_mega_link,
    is_rclone_path,
    is_telegram_link,
    is_url,
)
from bot.helper.listeners.task_listener import TaskListener
from bot.helper.mirror_leech_utils.download_utils.aria2_download import (
    add_aria2_download,
)
from bot.helper.mirror_leech_utils.download_utils.direct_downloader import (
    add_direct_download,
)
from bot.helper.mirror_leech_utils.download_utils.gd_download import add_gd_download
from bot.helper.mirror_leech_utils.download_utils.jd_download import add_jd_download
from bot.helper.mirror_leech_utils.download_utils.nzb_downloader import add_nzb
# from bot.helper.mirror_leech_utils.download_utils.direct_link_generator import (
#     direct_link_generator,
# )
from bot.helper.mirror_leech_utils.download_utils.qbit_download import add_qb_torrent
from bot.helper.mirror_leech_utils.download_utils.rclone_download import (
    add_rclone_download,
)
from bot.helper.mirror_leech_utils.download_utils.mega_download import (
    add_mega_download,
)
from bot.helper.mirror_leech_utils.download_utils.telegram_download import (
    TelegramDownloadHelper,
)
from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.ext_utils.limit_checker import limit_checker
from bot.helper.telegram_helper.message_utils import (
    auto_delete_message,
    delete_links,
    get_tg_link_message,
    send_message,
)
from bot.modules.media_tools import show_media_tools_for_task
from bot.modules.clone import Clone

class Mirror(TaskListener):
    def __init__(
        self,
        client,
        message,
        is_qbit=False,
        is_leech=False,
        is_jd=False,
        is_nzb=False,
        is_md_leech=False,
        is_enc=False,
        same_dir=None,
        bulk=None,
        multi_tag=None,
        options="",
        auto_link=None,
        auto_ff=None,
        name=None,
        size=None,
        **kwargs,
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
        self.auto_link = auto_link
        self.auto_ff = auto_ff
        self.name = name
        self.size = size
        super().__init__()
        self.is_qbit = is_qbit
        self.is_leech = is_leech
        self.is_jd = is_jd
        self.is_nzb = is_nzb
        self.is_md_leech = is_md_leech
        self.is_enc = is_enc

    def _ensure_user_dict(self):
        if not hasattr(self, "user_dict") or self.user_dict is None:
            from bot import user_data
            user_id = self.message.from_user.id if self.message.from_user else ""
            self.user_dict = user_data.get(user_id, {})

    async def new_event(self):
        # Ensure user_dict is never None to prevent AttributeError
        self._ensure_user_dict()

        # Check if message text exists before trying to split it
        if (
            not self.message
            or not hasattr(self.message, "text")
            or self.message.text is None
        ):
            LOGGER.error(
                "Message text is None or message doesn't have text attribute"
            )
            error_msg = "Invalid message format. Please make sure your message contains text."
            error = await send_message(self.message, error_msg)
            return await auto_delete_message(error, time=300)

        text = self.message.text.split("\n")
        input_list = text[0].split(" ")
        error_msg, error_button = await error_check(self.message)
        if error_msg:
            await delete_links(self.message)
            error = await send_message(self.message, error_msg, error_button)
            return await auto_delete_message(error, time=300)
        user_id = self.user_id
        args = {
            "-doc": False,
            "-med": False,
            "-d": False,
            "-j": False,
            "-s": False,
            "-b": False,
            "-e": False,
            "-z": False,
            "-sv": False,
            "-ss": False,
            "-f": False,
            "-fd": False,
            "-fu": False,
            "-hl": False,
            "-bt": False,
            "-ut": False,
            "-mt": False,
            "-merge-video": "",
            "-merge-audio": "",
            "-merge-subtitle": "",
            "-merge-all": False,
            "-merge-image": "",
            "-merge-pdf": "",
            "-i": 0,
            "-sp": 0,
            "link": "",
            "-n": "",
            "-m": "",  # Same directory operation flag
            "-watermark": "",
            "-iwm": "",
            "-up": "",
            "-rcf": "",
            "-au": "",
            "-ap": "",
            "-h": [],
            "-t": "",
            "-ca": "",
            "-cv": "",
            "-ns": "",
            "-md": "",
            "-metadata-title": "",
            "-metadata-author": "",
            "-metadata-comment": "",
            "-metadata-all": "",
            "-metadata-video-title": "",
            "-metadata-video-author": "",
            "-metadata-video-comment": "",
            "-metadata-audio-title": "",
            "-metadata-audio-author": "",
            "-metadata-audio-comment": "",
            "-metadata-subtitle-title": "",
            "-metadata-subtitle-author": "",
            "-metadata-subtitle-comment": "",
            "-tl": "",
            "-ff": set(),
            "-compress": False,
            "-comp-video": False,
            "-comp-audio": False,
            "-comp-image": False,
            "-comp-document": False,
            "-comp-subtitle": False,
            "-comp-archive": False,
            "-video-fast": False,
            "-video-medium": False,
            "-video-slow": False,
            "-audio-fast": False,
            "-audio-medium": False,
            "-audio-slow": False,
            "-image-fast": False,
            "-image-medium": False,
            "-image-slow": False,
            "-document-fast": False,
            "-document-medium": False,
            "-document-slow": False,
            "-subtitle-fast": False,
            "-subtitle-medium": False,
            "-subtitle-slow": False,
            "-archive-fast": False,
            "-archive-medium": False,
            "-archive-slow": False,
            "-trim": "",
            "-extract": False,
            "-extract-video": False,
            "-extract-audio": False,
            "-extract-subtitle": False,
            "-extract-attachment": False,
            "-extract-video-index": "",
            "-extract-audio-index": "",
            "-extract-subtitle-index": "",
            "-extract-attachment-index": "",
            "-extract-video-codec": "",
            "-extract-audio-codec": "",
            "-extract-subtitle-codec": "",
            "-extract-maintain-quality": "",
            "-extract-priority": "",
            "-remove": False,
            "-remove-video": False,
            "-remove-audio": False,
            "-remove-subtitle": False,
            "-remove-attachment": False,
            "-remove-metadata": False,
            "-remove-video-index": "",
            "-remove-audio-index": "",
            "-remove-subtitle-index": "",
            "-remove-attachment-index": "",
            "-remove-priority": "",
            "-add": False,
            "-add-video": False,
            "-add-audio": False,
            "-add-subtitle": False,
            "-add-attachment": False,
            "-del": "",
            "-preserve": False,
            "-replace": False,
            # Shorter index flags
            "-vi": "",
            "-ai": "",
            "-si": "",
            "-ati": "",
            # Remove shorter index flags
            "-rvi": "",
            "-rai": "",
            "-rsi": "",
            "-rati": "",
            # Swap flags
            "-swap": False,
            "-swap-audio": False,
            "-swap-video": False,
            "-swap-subtitle": False,
            "-lulu": False,
            "-buz": False,
            "-pix": False,
        }

        # AUTO LEECH + AUTO COMPRESS CMD
        if self.auto_link:
            # Inject link if not present (Auto Leech)
            if not any(x.startswith("http") or "magnet" in x for x in input_list):
                input_list.append(self.auto_link)

        # Check if user provided -ff
        user_ff = any(item.strip() == "-ff" for item in input_list)
        if not user_ff and self.auto_ff:
            # Append auto FFmpeg args
            input_list.extend(self.auto_ff.split())

        # Parse arguments from the command
        arg_parser(input_list[1:], args)

        # Check if media tools flags are enabled
        from bot.helper.ext_utils.bot_utils import is_flag_enabled

        # Disable flags that depend on disabled media tools
        for flag in list(args.keys()):
            if flag.startswith("-") and not is_flag_enabled(flag):
                if isinstance(args[flag], bool):
                    args[flag] = False
                elif isinstance(args[flag], set):
                    args[flag] = set()
                elif isinstance(args[flag], str):
                    args[flag] = ""
                elif isinstance(args[flag], int):
                    args[flag] = 0

        self.select = args["-s"]
        self.seed = args["-d"]
        self.name = args["-n"]
        self.up_dest = args["-up"]

        # Handle DEFAULT_UPLOAD and -up flag for various upload destinations
        if not self.is_leech:
            # Check user's DEFAULT_UPLOAD setting first, then fall back to global setting
            user_default_upload = self.user_dict.get(
                "DEFAULT_UPLOAD", Config.DEFAULT_UPLOAD
            )
            if user_default_upload == "gd" and not self.up_dest:
                self.up_dest = "gd"
            elif user_default_upload == "mg" and not self.up_dest:
                self.up_dest = "mg"
            elif user_default_upload == "yt" and not self.up_dest:
                self.up_dest = "yt"
            elif user_default_upload == "ddl" and not self.up_dest:
                self.up_dest = "ddl"

            if self.up_dest == "gd":
                # Validate Google Drive configuration
                if not Config.GDRIVE_UPLOAD_ENABLED:
                    await send_message(
                        self.message,
                        "❌ Google Drive upload is disabled by the administrator.",
                    )
                    return None
            elif self.up_dest == "mg":
                # Validate MEGA configuration
                if not Config.MEGA_ENABLED:
                    await send_message(
                        self.message,
                        "❌ MEGA.nz operations are disabled by the administrator.",
                    )
                    return None
                if not Config.MEGA_UPLOAD_ENABLED:
                    await send_message(
                        self.message,
                        "❌ MEGA upload is disabled by the administrator.",
                    )
                    return None

                # Check for user MEGA credentials first, then fall back to owner credentials
                user_mega_email = self.user_dict.get("MEGA_EMAIL")
                user_mega_password = self.user_dict.get("MEGA_PASSWORD")

                has_user_credentials = user_mega_email and user_mega_password
                has_owner_credentials = Config.MEGA_EMAIL and Config.MEGA_PASSWORD

                if not has_user_credentials and not has_owner_credentials:
                    await send_message(
                        self.message,
                        "❌ MEGA credentials not configured. Please set your MEGA credentials in user settings or contact the administrator.",
                    )
                    return None

                # Determine which account will be used and check if folder selection is needed

                # Always show MEGA folder selection since we removed upload folder config
                show_folder_selection = False

                # Show MEGA folder selection for all MEGA uploads
                if show_folder_selection:
                    from bot.helper.mirror_leech_utils.mega_utils.folder_selector import (
                        MegaFolderSelector,
                    )

                    folder_selector = MegaFolderSelector(self)
                    selected_path = await folder_selector.get_mega_path()

                    if selected_path is None:
                        # User cancelled
                        await self.remove_from_same_dir()
                        return None
                    if isinstance(selected_path, str) and selected_path.startswith(
                        "❌"
                    ):
                        # Error occurred
                        await send_message(self.message, selected_path)
                        await self.remove_from_same_dir()
                        return None
                    # Store selected path for this upload
                    self.mega_upload_path = selected_path
            elif self.up_dest == "yt":
                # Validate YouTube configuration
                if not Config.YOUTUBE_UPLOAD_ENABLED:
                    await send_message(
                        self.message,
                        "❌ YouTube upload is disabled by the administrator.",
                    )
                    return None
            elif self.up_dest == "ddl":
                # Validate DDL configuration
                if not Config.DDL_ENABLED:
                    await send_message(
                        self.message,
                        "❌ DDL upload is disabled by the administrator.",
                    )
                    return None

                # Check DDL server configuration
                from bot.modules.users_settings import get_ddl_setting

                user_id = self.message.from_user.id
                _default_server, _ = get_ddl_setting(user_id, "DDL_SERVER", "gofile")

        self.rc_flags = args["-rcf"]
        self.link = args["link"] or self.auto_link
        self.compress = args["-z"]
        # Enable compression if -z flag is set and archive flags are enabled
        from bot.helper.ext_utils.bot_utils import is_flag_enabled

        if self.compress and is_flag_enabled("-z"):
            self.compression_enabled = True
        self.extract = args["-e"]
        # Enable extract_enabled if -e flag is set and archive flags are enabled
        if self.extract and is_flag_enabled("-e"):
            self.extract_enabled = True

        # Add settings
        self.add_enabled = args["-add"]
        self.add_video_enabled = args["-add-video"]
        self.add_audio_enabled = args["-add-audio"]
        self.add_subtitle_enabled = args["-add-subtitle"]
        self.add_attachment_enabled = args["-add-attachment"]
        self.preserve_flag = args["-preserve"]
        self.replace_flag = args["-replace"]

        if self.name is None:
            self.name = args["name"]
        if self.size is None:
            self.size = 0

        # Remove settings
        self.remove_enabled = args["-remove"]
        self.remove_video_enabled = args["-remove-video"]
        self.remove_audio_enabled = args["-remove-audio"]
        self.remove_subtitle_enabled = args["-remove-subtitle"]
        self.remove_attachment_enabled = args["-remove-attachment"]
        self.remove_metadata = args["-remove-metadata"]

        # Handle remove index arguments
        self.remove_video_index = args["-remove-video-index"] or args["-rvi"]
        self.remove_audio_index = args["-remove-audio-index"] or args["-rai"]
        self.remove_subtitle_index = args["-remove-subtitle-index"] or args["-rsi"]
        self.remove_attachment_index = (
            args["-remove-attachment-index"] or args["-rati"]
        )

        # Enable remove if any specific remove flag is set
        if (
            self.remove_video_enabled
            or self.remove_audio_enabled
            or self.remove_subtitle_enabled
            or self.remove_attachment_enabled
            or self.remove_metadata
            or self.remove_video_index
            or self.remove_audio_index
            or self.remove_subtitle_index
            or self.remove_attachment_index
        ):
            self.remove_enabled = True
        self.join = args["-j"]
        self.thumb = args["-t"]
        self.split_size = args["-sp"]
        self.sample_video = args["-sv"]
        self.screen_shots = args["-ss"]
        self.force_run = args["-f"]
        self.force_download = args["-fd"]
        self.force_upload = args["-fu"]
        self.convert_audio = args["-ca"]
        self.convert_video = args["-cv"]
        self.name_sub = args["-ns"]
        self.hybrid_leech = args["-hl"]
        self.thumbnail_layout = args["-tl"]
        self.as_doc = args["-doc"]
        self.as_med = args["-med"]
        self.media_tools = args["-mt"]

        # Register user as pending task user if -mt flag is used
        if self.media_tools:
            from bot.modules.media_tools import register_pending_task_user

            register_pending_task_user(user_id)
        self.metadata = args["-md"]
        self.metadata_title = args["-metadata-title"]
        self.metadata_author = args["-metadata-author"]
        self.metadata_comment = args["-metadata-comment"]
        self.metadata_all = args["-metadata-all"]
        self.metadata_video_title = args["-metadata-video-title"]
        self.metadata_video_author = args["-metadata-video-author"]
        self.metadata_video_comment = args["-metadata-video-comment"]
        self.metadata_audio_title = args["-metadata-audio-title"]
        self.metadata_audio_author = args["-metadata-audio-author"]
        self.metadata_audio_comment = args["-metadata-audio-comment"]
        self.metadata_subtitle_title = args["-metadata-subtitle-title"]
        self.metadata_subtitle_author = args["-metadata-subtitle-author"]
        self.metadata_subtitle_comment = args["-metadata-subtitle-comment"]
        self.folder_name = (
            f"/{args['-m']}".rstrip("/") if len(args["-m"]) > 0 else ""
        )
        self.bot_trans = args["-bt"]
        self.user_trans = args["-ut"]
        self.merge_video = args["-merge-video"]
        self.merge_audio = args["-merge-audio"]
        self.merge_subtitle = args["-merge-subtitle"]
        self.merge_all = args["-merge-all"]
        self.merge_image = args["-merge-image"]
        self.merge_pdf = args["-merge-pdf"]
        self.watermark_text = args["-watermark"]
        self.watermark_image = args["-iwm"]
        self.trim = args["-trim"]
        self.ffmpeg_cmds = args["-ff"]
        # Upload hosters only work with /mirror, not /leech
        self.lulu = args["-lulu"] if not self.is_leech else False
        self.is_buzzheavier = args["-buz"] if not self.is_leech else False
        self.is_pixeldrain = args["-pix"] if not self.is_leech else False

        # Swap flags - merge command line flags with configuration
        # Command line flags enable swap functionality, but detailed config comes from database/settings
        if args["-swap"]:
            self.swap_enabled = True
        if args["-swap-audio"]:
            self.swap_audio_enabled = True
        if args["-swap-video"]:
            self.swap_video_enabled = True
        if args["-swap-subtitle"]:
            self.swap_subtitle_enabled = True

        # Enable swap if any specific swap flag is set
        if (
            self.swap_audio_enabled
            or self.swap_video_enabled
            or self.swap_subtitle_enabled
        ):
            self.swap_enabled = True

        # Compression flags
        self.compression_enabled = args["-compress"]
        self.compress_video = args["-comp-video"]
        self.compress_audio = args["-comp-audio"]
        self.compress_image = args["-comp-image"]
        self.compress_document = args["-comp-document"]
        self.compress_subtitle = args["-comp-subtitle"]
        self.compress_archive = args["-comp-archive"]

        self.yt_privacy = None
        self.yt_mode = None
        self.yt_tags = None
        self.yt_category = None
        self.yt_description = None

        if self.up_dest and self.up_dest.startswith("yt:"):
            self.raw_up_dest = "yt"
            parts = self.up_dest.split(":", 6)[1:]

            if len(parts) > 0 and parts[0]:
                self.yt_privacy = parts[0]
            if len(parts) > 1 and parts[1]:
                mode_candidate = parts[1]
                if mode_candidate in [
                    "playlist",
                    "individual",
                    "playlist_and_individual",
                ]:
                    self.yt_mode = mode_candidate
                elif mode_candidate:
                    LOGGER.warning(
                        f"Invalid YouTube upload mode in -up: {mode_candidate}. Ignoring mode override."
                    )
            if len(parts) > 2 and parts[2]:
                self.yt_tags = parts[2]
            if len(parts) > 3 and parts[3]:
                self.yt_category = parts[3]
            if len(parts) > 4 and parts[4]:
                self.yt_description = parts[4]
            if len(parts) > 5 and parts[5]:
                self.yt_playlist_id = parts[5]


        # Enable compression if any specific compression flag is set
        if (
            self.compress_video
            or self.compress_audio
            or self.compress_image
            or self.compress_document
            or self.compress_subtitle
            or self.compress_archive
        ):
            self.compression_enabled = True

        # Compression presets
        self.video_preset = None
        if args["-video-fast"]:
            self.video_preset = "fast"
        elif args["-video-medium"]:
            self.video_preset = "medium"
        elif args["-video-slow"]:
            self.video_preset = "slow"

        self.audio_preset = None
        if args["-audio-fast"]:
            self.audio_preset = "fast"
        elif args["-audio-medium"]:
            self.audio_preset = "medium"
        elif args["-audio-slow"]:
            self.audio_preset = "slow"

        self.image_preset = None
        if args["-image-fast"]:
            self.image_preset = "fast"
        elif args["-image-medium"]:
            self.image_preset = "medium"
        elif args["-image-slow"]:
            self.image_preset = "slow"

        self.document_preset = None
        if args["-document-fast"]:
            self.document_preset = "fast"
        elif args["-document-medium"]:
            self.document_preset = "medium"
        elif args["-document-slow"]:
            self.document_preset = "slow"

        self.subtitle_preset = None
        if args["-subtitle-fast"]:
            self.subtitle_preset = "fast"
        elif args["-subtitle-medium"]:
            self.subtitle_preset = "medium"
        elif args["-subtitle-slow"]:
            self.subtitle_preset = "slow"

        self.archive_preset = None
        if args["-archive-fast"]:
            self.archive_preset = "fast"
        elif args["-archive-medium"]:
            self.archive_preset = "medium"
        elif args["-archive-slow"]:
            self.archive_preset = "slow"

        headers = args["-h"]
        if headers:
            headers = headers.split("|")
        is_bulk = args["-b"]

        bulk_start = 0
        bulk_end = 0
        ratio = None
        seed_time = None
        reply_to = None
        file_ = None
        session = TgClient.bot

        try:
            # Check if multi-link operations are enabled in the configuration
            if not Config.MULTI_LINK_ENABLED and int(args["-i"]) > 0:
                await send_message(
                    self.message,
                    "❌ Multi-link operations are disabled by the administrator.",
                )
                self.multi = 0
            else:
                self.multi = int(args["-i"])
        except Exception:
            self.multi = 0

        # Check if same directory operations are enabled in the configuration
        if not Config.SAME_DIR_ENABLED and self.folder_name:
            await send_message(
                self.message,
                "❌ Same directory operations (-m flag) are disabled by the administrator.",
            )
            self.folder_name = None

        # Check if leech is disabled but leech-related flags are used
        if not Config.LEECH_ENABLED and (
            self.hybrid_leech
            or self.bot_trans
            or self.user_trans
            or self.thumbnail_layout
            or self.split_size
            or args.get("-es", False)
            or self.as_doc
            or self.as_med
        ):
            leech_flags_used = []
            if self.hybrid_leech:
                leech_flags_used.append("-hl")
            if self.bot_trans:
                leech_flags_used.append("-bt")
            if self.user_trans:
                leech_flags_used.append("-ut")
            if self.thumbnail_layout:
                leech_flags_used.append("-tl")
            if self.split_size:
                leech_flags_used.append("-sp")
            if args.get("-es", False):
                leech_flags_used.append("-es")
            if self.as_doc:
                leech_flags_used.append("-doc")
            if self.as_med:
                leech_flags_used.append("-med")

            flags_str = ", ".join(leech_flags_used)
            await send_message(
                self.message,
                f"❌ Leech operations are disabled by the administrator. Cannot use leech-related flags: {flags_str}",
            )
            # Reset leech-related flags
            self.hybrid_leech = False
            self.bot_trans = False
            self.user_trans = False
            self.thumbnail_layout = ""
            self.split_size = 0
            if "-es" in args: args["-es"] = False
            self.as_doc = False
            self.as_med = False

        # Initialize ratio and seed_time variables
        ratio = None
        seed_time = None

        # Check if torrent operations are disabled but torrent seed flag is used
        if not Config.TORRENT_ENABLED and self.seed:
            await send_message(
                self.message,
                "❌ Torrent operations are disabled by the administrator. Cannot use torrent seed flag: -d",
            )
            # Reset torrent seed flag
            self.seed = False

        if args["-ff"]:
            # Standardize to list of strings
            raw_input = args["-ff"]
            self.ffmpeg_cmds = []

            # Helper to get commands from keys
            def get_cmds_from_key(key):
                if Config.FFMPEG_CMDS and key in Config.FFMPEG_CMDS:
                    return Config.FFMPEG_CMDS[key]
                if (
                    self.user_dict.get("FFMPEG_CMDS")
                    and key in self.user_dict["FFMPEG_CMDS"]
                ):
                    return self.user_dict["FFMPEG_CMDS"][key]
                return None

            try:
                # 1. Handle Set of keys (e.g., from multiple flags)
                if isinstance(raw_input, set):
                    for key in raw_input:
                        cmds = get_cmds_from_key(key)
                        if cmds:
                            for cmd in cmds:
                                self.ffmpeg_cmds.append(cmd)
                        else:
                            # Treat as direct command if not found
                            pass  # Set usually implies presets, invalid keys are ignored or logged

                # 2. Handle List (could be mix of keys and commands, or direct command list)
                elif isinstance(raw_input, list):
                    for item in raw_input:
                        if isinstance(item, str):
                            # Try lookup first
                            cmds = get_cmds_from_key(item)
                            if cmds:
                                for cmd in cmds:
                                    self.ffmpeg_cmds.append(cmd)
                            else:
                                # Treat as direct command string
                                import shlex

                                self.ffmpeg_cmds.append(shlex.split(item))
                        elif isinstance(item, list):
                            # Already split command
                            self.ffmpeg_cmds.append(item)

                # 3. Handle Single String (Key or Command)
                elif isinstance(raw_input, str):
                    # Try lookup
                    cmds = get_cmds_from_key(raw_input)
                    if cmds:
                        for cmd in cmds:
                            self.ffmpeg_cmds.append(cmd)
                    else:
                        # Direct command
                        import shlex

                        # Check for multi-line/semicolon separated logic if needed,
                        # but usually it's one command or preset
                        if " " in raw_input and not any(
                            k in raw_input for k in (Config.FFMPEG_CMDS or {})
                        ):
                            # It's a command string like "-c copy"
                            self.ffmpeg_cmds.append(shlex.split(raw_input))
                        else:
                            # Maybe a key that wasn't found or a simple command
                            self.ffmpeg_cmds.append(shlex.split(raw_input))

                LOGGER.info(f"Resolved FFmpeg commands: {self.ffmpeg_cmds}")

            except Exception as e:
                self.ffmpeg_cmds = []
                LOGGER.error(f"Error processing FFmpeg command: {e}")

        if not isinstance(self.seed, bool):
            dargs = self.seed.split(":")
            ratio = dargs[0] or None
            if len(dargs) == 2:
                seed_time = dargs[1] or None
            self.seed = True

        if not isinstance(is_bulk, bool):
            dargs = is_bulk.split(":")
            bulk_start = int(dargs[0]) if dargs[0] else 0
            if len(dargs) == 2:
                bulk_end = int(dargs[1]) if dargs[1] else 0
            is_bulk = True

        # Check if bulk operations are enabled in the configuration
        if is_bulk and not Config.BULK_ENABLED:
            await send_message(
                self.message, "❌ Bulk operations are disabled by the administrator."
            )
            is_bulk = False


        # Extract bulk links if not already populated and not explicitly set as bulk
        if not is_bulk and len(self.bulk) == 0:
            from bot.helper.ext_utils.bulk_links import extract_bulk_links
            self.bulk = await extract_bulk_links(self.message, bulk_start, bulk_end)
            LOGGER.info(f"Extracted {len(self.bulk)} bulk links")
            if len(self.bulk) > 1:
                is_bulk = True


        if not is_bulk:
            if self.multi > 0:
                if self.folder_name:
                    async with task_dict_lock:
                        if self.folder_name in self.same_dir:
                            self.same_dir[self.folder_name]["tasks"].add(self.mid)
                            for fd_name in self.same_dir:
                                if fd_name != self.folder_name:
                                    self.same_dir[fd_name]["total"] -= 1
                        elif self.same_dir:
                            self.same_dir[self.folder_name] = {
                                "total": self.multi,
                                "tasks": {self.mid},
                            }
                            for fd_name in self.same_dir:
                                if fd_name != self.folder_name:
                                    self.same_dir[fd_name]["total"] -= 1
                        else:
                            self.same_dir = {
                                self.folder_name: {
                                    "total": self.multi,
                                    "tasks": {self.mid},
                                },
                            }
                elif self.same_dir:
                    async with task_dict_lock:
                        for fd_name in self.same_dir:
                            self.same_dir[fd_name]["total"] -= 1
        else:
            await self.init_bulk(input_list, bulk_start, bulk_end, Mirror)
            return None

        if len(self.bulk) != 0:
            del self.bulk[0]

        await self.run_multi(input_list, Mirror)

        await self.get_tag(text)

        path = f"{DOWNLOAD_DIR}{self.mid}{self.folder_name}"


        # Consolidated reply_to handling
        # Priority: Media > Caption Link > Command Link
        reply_to = self.message.reply_to_message
        if not reply_to and self.message.reply_to_message_id:
            reply_to = await self.client.get_messages(self.message.chat.id, self.message.reply_to_message_id)

        file_ = None
        if reply_to:
            file_ = (
                reply_to.document
                or reply_to.photo
                or reply_to.video
                or reply_to.audio
                or reply_to.voice
                or reply_to.video_note
                or reply_to.sticker
                or reply_to.animation
                or None
            )

            if file_:
                if reply_to.document and (
                    file_.mime_type == "application/x-bittorrent"
                    or file_.file_name.endswith((".torrent", ".dlc", ".nzb"))
                ):
                    self.link = await reply_to.download()
                    file_ = None
                else:
                    self.link = ""

        try:
            if (
                self.link
                and (is_magnet(self.link) or self.link.endswith(".torrent"))
            ) or (
                file_ and file_.file_name and file_.file_name.endswith(".torrent")
            ):
                if not Config.TORRENT_ENABLED:
                    await self.on_download_error(
                        "❌ Torrent operations are disabled by the administrator."
                    )
                    return None
                self.is_qbit = True
        except Exception:
            pass

        if (
            (not self.link and file_ is None)
            or (is_telegram_link(self.link) and reply_to is None)
            or (
                file_ is None
                and self.link
                and not is_url(self.link)
                and not is_magnet(self.link)
                and not await aiopath.exists(self.link)
                and not is_rclone_path(self.link)
                and not is_gdrive_id(self.link)
                and not is_gdrive_link(self.link)
                and not is_mega_link(self.link)
            )
        ):
            x = await send_message(
                self.message,
                COMMAND_USAGE["mirror"][0],
                COMMAND_USAGE["mirror"][1],
            )
            await self.remove_from_same_dir()
            await delete_links(self.message)
            return await auto_delete_message(x, time=300)

        # Check if media tools flag is set
        if self.media_tools:
            # Show media tools settings and wait for user to click Done or timeout
            proceed = await show_media_tools_for_task(
                self.client, self.message, self
            )
            if not proceed:
                # User cancelled or timeout occurred
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return None
        else:
            # Check if user has a direct result stored (fallback for race condition)
            from bot.modules.media_tools import direct_task_results

            if user_id in direct_task_results:
                result = direct_task_results[user_id]
                del direct_task_results[user_id]
                if not result:
                    # User clicked Cancel
                    await self.remove_from_same_dir()
                    await delete_links(self.message)
                    return None
                # If result is True, continue with the task

        try:
            await self.before_start()
        except Exception as e:
            # Convert exception to string to avoid TypeError in send_message
            error_msg = (
                str(e) if e else "An unknown error occurred during initialization"
            )
            x = await send_message(self.message, error_msg)
            await self.remove_from_same_dir()
            await delete_links(self.message)
            return await auto_delete_message(x, time=300)

        # Get file size for limit checking
        size = 0
        if file_:
            size = file_.file_size

        # Check limits before proceeding
        if size > 0:
            limit_msg = await limit_checker(self)
            if limit_msg:
                # limit_msg is already a tuple with (message_object, error_message)
                # and the message has already been sent with the tag
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return None
        if (
            not self.is_jd
            and not self.is_qbit
            and not self.is_nzb
            and not is_magnet(self.link)
            and not is_mega_link(self.link)
            and not is_rclone_path(self.link)
            and not is_gdrive_link(self.link)
            and not is_gdrive_id(self.link)
            and not self.link.endswith(".torrent")
            and not await aiopath.exists(self.link)
            and file_ is None
        ):
            content_type = await get_content_type(self.link)
            if content_type and "x-bittorrent" in content_type:
                self.is_qbit = True
            if content_type is None or re_match(
                r"text/html|text/plain",
                content_type,
            ):
                resolver = TrueLinkResolver()
                try:
                    if resolver.is_supported(self.link):
                        result = await resolver.resolve(self.link)
                        if result:
                            if isinstance(result, LinkResult):
                                self.link = result.url
                                if not self.name:
                                    self.name = result.filename
                                if result.headers:
                                    headers = [
                                        f"{k}: {v}" for k, v in result.headers.items()
                                    ]
                            elif isinstance(result, FolderResult):
                                # Handle folder result and exit early
                                await add_direct_download(self, path)
                                await delete_links(self.message)
                                return None
                            else:
                                self.link = result
                except TrueLinkException as e:
                    x = await send_message(self.message, e)
                    await self.remove_from_same_dir()
                    await delete_links(self.message)
                    return await auto_delete_message(x, time=300)
                except Exception as e:
                    LOGGER.error(f"Unexpected exception in resolver: {e}")
                    x = await send_message(
                        self.message, "An unexpected error occurred."
                    )
                    await self.remove_from_same_dir()
                    await delete_links(self.message)
                    return await auto_delete_message(x, time=300)

                # Fallback to direct_link_generator with improved error handling
                # Only if resolver didn't handle it and link has proper protocol
                if not resolver.is_supported(self.link) and (
                    (self.link and ("://" in self.link or self.link.startswith("magnet:")))
                    or is_magnet(self.link)
                ):
                    try:
                        from bot.helper.ext_utils.bot_utils import sync_to_async
                        from bot.helper.mirror_leech_utils.download_utils.direct_link_generator import direct_link_generator
                        res = await sync_to_async(direct_link_generator, self.link)
                        if isinstance(res, dict):
                            # Handle folder results or detailed link info
                            if "links" in res and res["links"]:
                                # If it's a folder, we might need bulk handling or just take the first link
                                # For simplicity, we'll take the first link or notify if it's too complex
                                self.link = res["links"][0]
                            else:
                                self.link = res.get("url", self.link)
                        elif isinstance(res, str):
                            self.link = res
                    except DirectDownloadLinkException as e:
                        e = str(e)
                        if "ERROR: File not found" in e:
                            await self.on_download_error("❌ File not found. The link might be dead or expired.")
                            return None
                        elif "ERROR: User download limit reached" in e:
                            await self.on_download_error("❌ Download limit reached for this host. Please try again later or use a different service.")
                            return None
                        elif "ERROR: Password required" in e:
                            await self.on_download_error("❌ Password required. Please provide the password using -up flag if supported.")
                            return None
                        elif "ERROR: Invalid URL" in e:
                            # Might be a local file or something else, handled below
                            pass
                        else:
                            await self.on_download_error(f"❌ Direct link generation failed: {e}")
                            return None
                    except Exception as e:
                        LOGGER.error(f"Direct link generation failed: {e}")

        # Final check for local file existence if link is not a URL
        if (
            not is_url(self.link)
            and not is_magnet(self.link)
            and not await aiopath.exists(self.link)
            and not is_rclone_path(self.link)
            and not is_gdrive_id(self.link)
            and not is_mega_link(self.link)
            and file_ is None
        ):
            await self.on_download_error(
                f"❌ Invalid link or file path: {self.link}"
            )
            return None

        # Recheck limits with resolved link if changed
        if is_url(self.link) and not file_:
            # We don't have the size for most direct links yet,
            # but we can check if it's Mega or Drive
            limit_msg = await limit_checker(self)
            if limit_msg:
                # limit_msg is already handled by limit_checker
                await self.remove_from_same_dir()
                await delete_links(self.message)
                return None

        # Route to appropriate download handler based on link/file type
        if file_ is not None:
            create_task(
                TelegramDownloadHelper(self).add_download(
                    reply_to,
                    f"{path}/",
                    session,
                ),
            )
        elif self.is_jd:
            await add_jd_download(self, path)
        elif self.is_qbit:
            await add_qb_torrent(self, path, ratio, seed_time)
        elif self.is_nzb:
            await add_nzb(self, path)
        elif is_mega_link(self.link):
            await add_mega_download(self, path)
        elif is_rclone_path(self.link):
            await add_rclone_download(self, path)
        elif is_gdrive_link(self.link) or is_gdrive_id(self.link):
            await add_gd_download(self, path)
        else:
            # Direct download with optional authentication
            ussr = args.get("-au")
            pssw = args.get("-ap")
            if ussr or pssw:
                auth = f"{ussr}:{pssw}"
                headers.extend([
                    f"authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
                ])
            await add_aria2_download(self, path, headers, ratio, seed_time)

        await delete_links(self.message)
        return None

async def mirror(client, message):
    bot_loop.create_task(Mirror(client, message).new_event())


async def leech(client, message):
    if not Config.LEECH_ENABLED:
        return await send_message(
            message, "❌ Leech is disabled by the administrator."
        )
    bot_loop.create_task(Mirror(client, message, is_leech=True).new_event())


async def jd_mirror(client, message):
    if not Config.JD_ENABLED:
        return await send_message(
            message, "❌ JDownloader is disabled by the administrator."
        )
    bot_loop.create_task(Mirror(client, message, is_jd=True).new_event())


async def nzb_mirror(client, message):
    if not Config.NZB_ENABLED:
        return await send_message(
            message, "❌ NZB is disabled by the administrator."
        )
    bot_loop.create_task(Mirror(client, message, is_nzb=True).new_event())


async def jd_leech(client, message):
    if not Config.JD_ENABLED:
        return await send_message(
            message, "❌ JDownloader is disabled by the administrator."
        )
    if not Config.LEECH_ENABLED:
        return await send_message(
            message, "❌ Leech is disabled by the administrator."
        )
    bot_loop.create_task(
        Mirror(client, message, is_leech=True, is_jd=True).new_event()
    )


async def nzb_leech(client, message):
    if not Config.NZB_ENABLED:
        return await send_message(
            message, "❌ NZB is disabled by the administrator."
        )
    if not Config.LEECH_ENABLED:
        return await send_message(
            message, "❌ Leech is disabled by the administrator."
        )
    bot_loop.create_task(
        Mirror(client, message, is_leech=True, is_nzb=True).new_event()
    )


async def md_leech_node(client, message):
    if not Config.LEECH_ENABLED:
        return await send_message(
            message, "❌ Leech is disabled by the administrator."
        )
    bot_loop.create_task(
        Mirror(client, message, is_leech=True, is_md_leech=True).new_event()
    )
