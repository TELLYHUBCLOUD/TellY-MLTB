import asyncio
import re
from os import path as ospath
from os import walk
from typing import Any, Dict, List, Optional, Tuple, Union

from aiofiles.os import makedirs, remove

from bot import LOGGER, bot_loop, task_dict, task_dict_lock

MERGE_SESSIONS = {}

from bot.helper.aeon_utils.access_check import error_check
from bot.helper.ext_utils.bot_utils import (
    arg_parser,
    async_thread_executor,
    get_readable_file_size,
    new_task,
    sync_to_async,
)
from bot.helper.ext_utils.exceptions import NotSupportedFormatError
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
    update_status_message,
)


class MergeMode(Enum):
    CONCAT = "concat"
    CONCAT_DEMUX = "concat_demux"
    COMPLEX = "complex"


@dataclass
class MergeFile:
    path: str
    original_name: str
    index: int
    size: int = 0
    duration: float = 0.0
    codecs: Dict[str, List[str]] = field(default_factory=dict)
    is_valid: bool = True
    error: str = ""


class MergeSession:
    """Manages merge sessions for users with validation and limits."""
    
    MAX_FILES = 20
    MAX_TOTAL_SIZE = 8 * 1024 * 1024 * 1024  # 8GB total limit
    
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
    
    def get_session(self, user_id: int) -> Optional[Dict]:
        return self.sessions.get(user_id)
    
    def create_session(self, user_id: int, message, client) -> Dict:
        self.sessions[user_id] = {
            "inputs": [],
            "message": message,
            "client": client,
            "total_size": 0,
            "created_at": asyncio.get_event_loop().time(),
            "last_updated": asyncio.get_event_loop().time(),
        }
        return self.sessions[user_id]
    
    def add_file(self, user_id: int, file_input: Any) -> Tuple[bool, str]:
        session = self.get_session(user_id)
        if not session:
            return False, "No active session"
        
        if len(session["inputs"]) >= self.MAX_FILES:
            return False, f"Maximum file limit reached ({self.MAX_FILES})"
        
        # Check for duplicates
        input_id = self._get_input_id(file_input)
        if any(self._get_input_id(f) == input_id for f in session["inputs"]):
            return False, "File already added to session"
        
        # Estimate size for URLs/links
        estimated_size = self._estimate_file_size(file_input)
        if estimated_size > 0:
            new_total = session["total_size"] + estimated_size
            if new_total > self.MAX_TOTAL_SIZE:
                return False, f"Total size would exceed limit ({get_readable_file_size(self.MAX_TOTAL_SIZE)})"
            session["total_size"] = new_total
        
        session["inputs"].append(file_input)
        session["last_updated"] = asyncio.get_event_loop().time()
        return True, f"File added successfully ({len(session['inputs'])}/{self.MAX_FILES})"
    
    def cleanup_session(self, user_id: int):
        if user_id in self.sessions:
            del self.sessions[user_id]
    
    def _get_input_id(self, file_input: Any) -> str:
        if hasattr(file_input, "id"):
            return str(file_input.id)
        elif hasattr(file_input, "message_id"):
            return str(file_input.message_id)
        return str(file_input).split("/")[-1][:20]  # For URLs
    
    def _estimate_file_size(self, file_input: Any) -> int:
        """Estimate file size for validation before download"""
        if hasattr(file_input, "document") and file_input.document:
            return file_input.document.file_size or 0
        elif hasattr(file_input, "video") and file_input.video:
            return file_input.video.file_size or 0
        elif isinstance(file_input, str) and (is_url(file_input) or is_telegram_link(file_input)):
            # Default estimate for URLs - will be refined after download
            return 100 * 1024 * 1024  # 100MB estimate
        return 0
    
    def get_session_status(self, user_id: int) -> str:
        session = self.get_session(user_id)
        if not session:
            return "No active session"
        
        count = len(session["inputs"])
        size_str = get_readable_file_size(session["total_size"]) if session["total_size"] > 0 else "Unknown"
        remaining = self.MAX_FILES - count
        
        return (
            f"📁 <b>Merge Session Active</b>\n\n"
            f"Files Added: <code>{count}/{self.MAX_FILES}</code>\n"
            f"Estimated Total Size: <code>{size_str}</code>\n"
            f"Remaining Slots: <code>{remaining}</code>\n\n"
            f"Use /{BotCommands.MdoneCommand[0]} to start merging when ready."
        )


MERGE_SESSIONS = MergeSession()


class MergeUtils:
    """Utility methods for merge operations"""
    
    @staticmethod
    async def detect_media_type(file_path: str) -> str:
        """Detect if file is video, audio, or subtitle"""
        try:
            codecs = await get_codec_info(file_path)
            if any(c.startswith('video') for c in codecs.get('video', [])):
                return "video"
            elif any(c.startswith('audio') for c in codecs.get('audio', [])):
                return "audio"
            elif codecs.get('subtitle'):
                return "subtitle"
        except Exception as e:
            LOGGER.warning(f"Error detecting media type for {file_path}: {e}")
        return "unknown"
    
    @staticmethod
    async def validate_merge_compatibility(files: List[MergeFile]) -> Tuple[bool, str]:
        """Validate if files can be merged together"""
        if len(files) < 2:
            return False, "Need at least 2 files to merge"
        
        # Check for valid files
        valid_files = [f for f in files if f.is_valid]
        if len(valid_files) < 2:
            return False, f"Only {len(valid_files)} valid files found for merging"
        
        # Group by media type
        media_types = defaultdict(list)
        for file in valid_files:
            mtype = await MergeUtils.detect_media_type(file.path)
            media_types[mtype].append(file)
        
        # If we have mixed types, need complex filter
        if len(media_types) > 1:
            if "video" not in media_types:
                return False, "Cannot merge without at least one video file"
        
        # Check codec compatibility for direct concat
        if len(media_types.get("video", [])) > 1:
            first_video = media_types["video"][0]
            for video in media_types["video"][1:]:
                if not await validate_codec(first_video.path, video.path):
                    return True, "Files have incompatible codecs - will use slower conversion method"
        
        return True, "Files are compatible for merging"
    
    @staticmethod
    async def generate_output_name(files: List[MergeFile], suffix: str = "") -> str:
        """Generate smart output name from input files"""
        try:
            # Extract base names without extensions
            base_names = [ospath.splitext(f.original_name)[0] for f in files]
            
            # Common patterns for series/anime
            patterns = [
                (r"(.*?)(?:S|Season)?\s*(\d+)(?:E|Ep|Episode)?\s*(\d+)", "series"),
                (r"(.*?)(?:Part|Pt|P)\.?\s*(\d+)", "part"),
                (r"(.*?)(\d+)$", "numbered"),
            ]
            
            for pattern, ptype in patterns:
                matches = []
                for name in base_names:
                    match = re.search(pattern, name, re.IGNORECASE)
                    if match:
                        matches.append(match.groups())
                
                if len(matches) == len(files):
                    # All files match this pattern
                    prefix = matches[0][0].strip()
                    nums = [int(m[-1]) for m in matches]
                    
                    if ptype == "series":
                        season = matches[0][1]
                        start_ep = min(nums)
                        end_ep = max(nums)
                        name = f"{prefix} S{season}E{start_ep:02d}-E{end_ep:02d}"
                    elif ptype == "part":
                        start_part = min(nums)
                        end_part = max(nums)
                        name = f"{prefix} Part{start_part}-{end_part}"
                    else:  # numbered
                        start_num = min(nums)
                        end_num = max(nums)
                        name = f"{prefix} {start_num}-{end_num}"
                    
                    # Determine extension based on content
                    has_video = any(await MergeUtils.detect_media_type(f.path) == "video" for f in files)
                    has_ass = any("ass" in str(f.codecs) or "ssa" in str(f.codecs) for f in files)
                    
                    ext = ".mkv" if has_ass else (".mp4" if has_video else ".mkv")
                    return f"{name}{suffix}{ext}"
            
            # Fallback to first file name with merge indicator
            first_name = ospath.splitext(files[0].original_name)[0]
            return f"{first_name}_merged{suffix}.mp4"
        
        except Exception as e:
            LOGGER.error(f"Error generating output name: {e}")
            return f"merged_video{suffix}.mp4"


class Merge(TaskListener):
    """Handles merging of multiple media files into a single output with improved architecture."""
    
    MIN_CHUNK_SIZE = 50 * 1024 * 1024  # 50MB
    
    def __init__(self, client, message, **kwargs):
        self.message = message
        self.client = client
        super().__init__()
        self.is_leech = True
        self.is_merge = True
        self.is_leech = True
        
        # Configuration options
        self.output_name = kwargs.get("-n", "")
        self.name_subfix = kwargs.get("suffix", "")
        self.up_dest = kwargs.get("-up", "")
        self.rc_flags = kwargs.get("-rcf", "")
        self.multi = kwargs.get("-i", 0)
        
        # Processing state
        self.inputs: List[Any] = []
        self.files: List[MergeFile] = []
        self.total_batch_files = 0
        self.current_batch_files = 0
        self.merge_mode = MergeMode.CONCAT
        self.has_ass_subtitle = False
        self.total_size = 0
        
        # Session handling
        self.is_session_start = kwargs.get("is_session_start", False)
        self.is_session_done = kwargs.get("is_session_done", False)
    
    async def new_event(self):
        """Main entry point for merge command processing."""
        text = self.message.text.split("\n")
        input_list = text[0].split(" ")

        # Error checking
        error_msg, error_button = await error_check(self.message)
        if error_msg:
            await self._handle_error(error_msg, error_button)
            return
        
        # Parse arguments
        text = self.message.text.split("\n")
        input_list = text[0].split(" ")
        args = self._parse_arguments(input_list[1:])
        await self.get_tag(text)
        
        # Handle special session commands
        if self.is_session_start:
            await self._handle_session_start()
            return
        if self.is_session_done:
            await self._handle_session_done(args)
            return
        
        # Parse inputs from message
        self.inputs = await self._parse_all_inputs(text, args)
        
        # Validate inputs
        if not self.inputs:
            await send_message(
                self.message,
                f"⚠️ No valid inputs found!\n\n"
                f"Usage:\n"
                f"- Reply to media files\n"
                f"- Send links (one per line)\n"
                f"- Use Telegram link ranges (e.g., https://t.me/channel/10-20)\n"
                f"- Start a session with /{BotCommands.MergeCommand[0]}"
            )
            return
        
        # Handle bulk processing
        if len(self.inputs) > 1 and not args["-b"]:
            await self._handle_bulk_processing(input_list, args)
            return
        
        # Single file handling - add to session
        if len(self.inputs) == 1:
            await self._handle_single_file_session()
            return
        
        # Validate merge limit
        if len(self.inputs) > MERGE_SESSIONS.MAX_FILES:
            await send_message(
                self.message,
                f"⚠️ <b>Merge Limit Exceeded</b>\n"
                f"You can merge up to <code>{MERGE_SESSIONS.MAX_FILES}</code> files at once.\n"
                f"Found: <code>{len(self.inputs)}</code> inputs."
            )
            return
        
        await self._process_merge_request()
    
    def _parse_arguments(self, args_list: List[str]) -> Dict:
        """Parse command arguments with validation."""
        args = {
            "link": "",
            "-i": 0,
            "-n": "",
            "-up": "",
            "-rcf": "",
            "-b": False,
            "-mode": "auto",
        }
        arg_parser(args_list, args)
        
        # Validate merge mode
        if args["-mode"] not in ["auto", "concat", "demux", "complex"]:
            args["-mode"] = "auto"
        
        return args
    
    async def _parse_all_inputs(self, text_lines: List[str], args: Dict) -> List[Any]:
        """Parse all possible inputs from message with validation."""
        inputs = []
        
        # Add link argument if provided
        if args["link"] and (is_url(args["link"]) or is_telegram_link(args["link"])):
            inputs.append(args["link"])
        
        # Parse text lines for links
        for line in text_lines:
            line = line.strip()
            if not line:
                continue
            
            # Handle Telegram range links
            if is_telegram_link(line):
                range_inputs = self._parse_telegram_range(line)
                if range_inputs:
                    inputs.extend(range_inputs)
                    continue
            
            # Handle regular URLs
            if is_url(line):
                inputs.append(line)
        
        # Handle reply to media
        if not inputs and self.message.reply_to_message:
            reply = self.message.reply_to_message
            if reply.document or reply.video or reply.audio:
                inputs.append(reply)
        
        # Deduplicate inputs
        return self._deduplicate_inputs(inputs)
    
    def _parse_telegram_range(self, link: str) -> List[str]:
        """Parse Telegram link range with validation."""
        match = re.search(r"(https?://t\.me/(?:c/)?([\w\d_]+)/)(\d+)-(\d+)", link)
        if match:
            base = match.group(1)
            start = int(match.group(3))
            end = int(match.group(4))
            
            if end - start > MERGE_SESSIONS.MAX_FILES:
                end = start + MERGE_SESSIONS.MAX_FILES - 1
                LOGGER.warning(f"Trimmed Telegram range to respect max files limit: {start}-{end}")
            
            if start <= end:
                return [f"{base}{i}" for i in range(start, end + 1)]
        return []
    
    def _deduplicate_inputs(self, inputs: List[Any]) -> List[Any]:
        """Remove duplicate inputs while preserving order."""
        seen = set()
        unique_inputs = []
        
        for inp in inputs:
            inp_str = str(inp) if not hasattr(inp, "id") else str(inp.id)
            if inp_str not in seen:
                seen.add(inp_str)
                unique_inputs.append(inp)
        
        if len(unique_inputs) != len(inputs):
            LOGGER.info(f"Deduplicated inputs: {len(inputs)} -> {len(unique_inputs)}")
        
        return unique_inputs
    
    def _get_input_identifier(self, inp: Any) -> str:
        """Get unique identifier for input deduplication."""
        if hasattr(inp, "id"):
            return str(inp.id)
        elif hasattr(inp, "message_id"):
            return str(inp.message_id)
        elif isinstance(inp, str):
            return inp.split("?")[0]  # Remove query parameters
        return str(hash(str(inp)))
    
    async def _handle_error(self, error_msg: str, error_button: Any = None):
        """Handle errors with proper cleanup."""
        await delete_links(self.message)
        error = await send_message(self.message, error_msg, error_button)
        await auto_delete_message(error, time=300)
    
    async def _handle_session_start(self):
        """Handle starting a new merge session."""
        user_id = self.message.from_user.id
        session = MERGE_SESSIONS.get_session(user_id)
        
        if session:
            status = MERGE_SESSIONS.get_session_status(user_id)
            await send_message(self.message, status)
        else:
            count = len(MERGE_SESSIONS[user_id]["inputs"])
            await send_message(
                self.message,
                f"✅ <b>Merge Session Started!</b>\n\n"
                f"📥 <b>How to add files:</b>\n"
                f"• Reply to this message with media files\n"
                f"• Forward messages with media\n"
                f"• Send download links (one per message)\n\n"
                f"📁 <b>Limit:</b> {MERGE_SESSIONS.MAX_FILES} files\n"
                f"💾 <b>Max Total Size:</b> {get_readable_file_size(MERGE_SESSIONS.MAX_TOTAL_SIZE)}\n\n"
                f"✅ Use /{BotCommands.MdoneCommand[0]} when ready to merge!"
            )
    
    async def _handle_session_done(self, args: Dict):
        """Handle completion of a merge session."""
        user_id = self.message.from_user.id
        session = MERGE_SESSIONS.get_session(user_id)
        
        if not session:
            await send_message(
                self.message,
                f"❌ <b>No Active Session</b>\n"
                f"Start a session with /{BotCommands.MergeCommand[0]} first."
            )
            return
        
        if len(session["inputs"]) < 2:
            await send_message(
                self.message,
                f"❌ <b>Insufficient Files</b>\n"
                f"Need at least <code>2</code> files to merge.\n"
                f"Current: <code>{len(session['inputs'])}</code>"
            )
            return
        
        # Setup merge with session inputs
        self.inputs = session["inputs"]
        self.output_name = args.get("-n", "")
        self.up_dest = args.get("-up", "")
        self.rc_flags = args.get("-rcf", "")
        
        if not self.output_name and len(self.message.text.split()) > 1:
            # Use rest of command as suffix
            suffix = " ".join(self.message.text.split()[1:])
            if not suffix.startswith("-"):
                self.name_subfix = f" {suffix.strip()}"
        
        # Cleanup session before processing
        MERGE_SESSIONS.cleanup_session(user_id)
        
        await send_message(
            self.message,
            f"🔄 <b>Starting Merge Process</b>\n"
            f"Files to merge: <code>{len(self.inputs)}</code>\n"
            f"Please wait while files are downloaded and processed..."
        )
        
        await self._process_merge_request()
    
    async def _handle_single_file_session(self):
        """Handle adding a single file to a merge session."""
        user_id = self.message.from_user.id
        session = MERGE_SESSIONS.get_session(user_id)
        
        if not session:
            # Create session if none exists
            session = MERGE_SESSIONS.create_session(user_id, self.message, self.client)
        
        # Add file to session
        success, msg = MERGE_SESSIONS.add_file(user_id, self.inputs[0])
        
        if success:
            status = MERGE_SESSIONS.get_session_status(user_id)
            await send_message(self.message, status)
        else:
            await send_message(self.message, f"❌ <b>Failed to add file:</b>\n{msg}")
    
    async def _handle_bulk_processing(self, input_list: List[str], args: Dict):
        """Handle bulk processing of multiple merge requests."""
        await self.init_bulk(input_list, 0, 0, Merge)
    
    async def _process_merge_request(self):
        """Main processing workflow for merge requests."""
        try:
            await self.before_start()
            
            # Create directory structure
            await makedirs(self.dir, exist_ok=True)
            
            # Download and validate all files
            await self._download_and_validate_files()
            
            # Validate merge compatibility
            can_merge, reason = await MergeUtils.validate_merge_compatibility(self.files)
            if not can_merge:
                await self.on_upload_error(f"❌ Merge Validation Failed:\n{reason}")
                return
            
            # Determine merge mode
            self.merge_mode = await self._determine_merge_mode()
            
            # Generate output name if not provided
            if not self.output_name:
                self.output_name = await MergeUtils.generate_output_name(
                    self.files, self.name_subfix
                )
            else:
                # Apply suffix and ensure proper extension
                name, ext = ospath.splitext(self.output_name)
                if self.has_ass_subtitle and ext.lower() != ".mkv":
                    ext = ".mkv"
                elif not ext:
                    ext = ".mp4"
                self.output_name = f"{name}{self.name_subfix}{ext}"
            
            self.name = f"[Merge] {self.output_name}"
            await send_status_message(self.message)
            
            # Execute merge based on mode
            if self.merge_mode == MergeMode.CONCAT:
                await self._execute_concat_merge()
            elif self.merge_mode == MergeMode.CONCAT_DEMUX:
                await self._execute_demux_merge()
            else:
                await self._execute_complex_merge()
            
        except Exception as e:
            LOGGER.exception(f"Merge processing failed: {str(e)}")
            await self.on_upload_error(f"❌ Merge Processing Failed:\n{str(e)}")
    
    async def _download_and_validate_files(self):
        """Download all files and validate their media properties."""
        self.total_batch_files = len(self.inputs)
        self.files = []
        
        for idx, inp in enumerate(self.inputs):
            if self.is_cancelled:
                raise Exception("Task cancelled by user")
            
            # Create subdirectory for each file
            file_dir = f"{self.dir}/{idx}/"
            await makedirs(file_dir, exist_ok=True)
            
            # Download file
            file_path = await self._download_single_file(inp, file_dir, idx)
            if not file_path or not await aiopath.exists(file_path):
                LOGGER.error(f"Download failed for input {idx}")
                continue
            
            # Get file properties
            file_size = (await stat(file_path)).st_size
            file_name = ospath.basename(file_path)
            
            # Get media info
            try:
                duration, _, _ = await get_media_info(file_path)
                codecs = await get_codec_info(file_path)
                
                # Check for ASS/SSA subtitles
                if any(codec in ["ass", "ssa"] for streams in codecs.values() for codec in streams):
                    self.has_ass_subtitle = True
                
                self.files.append(MergeFile(
                    path=file_path,
                    original_name=file_name,
                    index=idx,
                    size=file_size,
                    duration=duration,
                    codecs=codecs,
                    is_valid=True
                ))
                self.total_size += file_size
                
            except Exception as e:
                LOGGER.error(f"Error analyzing file {file_path}: {str(e)}")
                self.files.append(MergeFile(
                    path=file_path,
                    original_name=file_name,
                    index=idx,
                    is_valid=False,
                    error=str(e)
                ))
        
        # Filter out invalid files
        valid_files = [f for f in self.files if f.is_valid]
        if len(valid_files) < 2:
            invalid_count = len(self.files) - len(valid_files)
            raise Exception(
                f"Insufficient valid files for merging. "
                f"Valid: {len(valid_files)}, Invalid: {invalid_count}"
            )
        
        self.files = valid_files
        self.total_batch_files = len(valid_files)
    
    async def _download_single_file(self, inp: Any, directory: str, index: int) -> Optional[str]:
        """Download a single file with proper naming and progress tracking."""
        from bot.helper.mirror_leech_utils.download_utils.telegram_download import (
            TelegramDownloadHelper,
        )
        
        try:
            if hasattr(inp, "document") or hasattr(inp, "video") or hasattr(inp, "audio"):
                # Telegram media
                media = inp.document or inp.video or inp.audio
                self.name = f"[{index+1}/{self.total_batch_files}] {media.file_name}"
                await TelegramDownloadHelper(self).add_download(inp, directory, self.client)
                
            elif isinstance(inp, str):
                if is_telegram_link(inp):
                    # Telegram message link
                    message = await self._get_tg_message_from_link(inp)
                    if message and (message.document or message.video or message.audio):
                        media = message.document or message.video or message.audio
                        self.name = f"[{index+1}/{self.total_batch_files}] {media.file_name}"
                        await TelegramDownloadHelper(self).add_download(message, directory, self.client)
                    else:
                        raise Exception("Invalid Telegram link or no media found")
                
                elif is_url(inp):
                    # Regular URL
                    self.link = inp
                    self.name = f"[{index+1}/{self.total_batch_files}] {ospath.basename(inp)}"
                    await add_aria2_download(self, directory, [], None, None)
            
            # Return the downloaded file path
            for root, _, files in await sync_to_async(walk, directory):
                for file in files:
                    return ospath.join(root, file)
            
            return None
            
        except Exception as e:
            LOGGER.error(f"Download error for input {index}: {str(e)}")
            raise
    
    async def _get_tg_message_from_link(self, link: str):
        """Safely get Telegram message from link with error handling."""
        if not is_telegram_link(link):
            return None

        try:
            match = re.search(
                r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:c/)?([\w\d_]+)/(\d+)",
                link
            )
            match = re.search(pattern, link)

            if not match:
                raise ValueError("Invalid Telegram link format")
            
            chat_identifier = match.group(1)
            msg_id = int(match.group(2))
            
            # Handle channel IDs
            if "c/" in link or chat_identifier.isdigit():
                chat_id = int(f"-100{chat_identifier}") if not chat_identifier.startswith("-100") else int(chat_identifier)
            else:
                chat_id = chat_identifier
            
            return await self.client.get_messages(chat_id, msg_id)

        except Exception as e:
            LOGGER.error(f"Error fetching Telegram message from {link}: {str(e)}")
            return None
    
    async def _determine_merge_mode(self) -> MergeMode:
        """Determine the optimal merge mode based on file properties."""
        try:
            # Check if all files have compatible codecs for direct concat
            first_file = self.files[0]
            for file in self.files[1:]:
                if not await validate_codec(first_file.path, file.path):
                    LOGGER.info("Found incompatible codecs, using demux concat mode")
                    return MergeMode.CONCAT_DEMUX
            
            # Check for mixed media types requiring complex filter
            media_types = set()
            for file in self.files:
                mtype = await MergeUtils.detect_media_type(file.path)
                media_types.add(mtype)
            
            if len(media_types) > 1 and "video" in media_types:
                LOGGER.info("Mixed media types detected, using complex merge mode")
                return MergeMode.COMPLEX
            
            return MergeMode.CONCAT
            
        except Exception as e:
            LOGGER.warning(f"Error determining merge mode: {str(e)}, defaulting to demux mode")
            return MergeMode.CONCAT_DEMUX
    
    async def _execute_concat_merge(self):
        """Execute fast concat merge using FFmpeg concat protocol."""
        input_txt_path = f"{self.dir}/input.txt"
        
        # Create concat file
        async with aiopen(input_txt_path, "w") as f:
            for file in self.files:
                escaped_path = file.path.replace("'", "'\\''")
                await f.write(f"file '{escaped_path}'\n")
        
        # Build command
        output_path = f"{self.dir}/{self.output_name}"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", input_txt_path,
            "-map", "0", "-c", "copy",
            "-metadata", f"title={self.tag}",
            "-movflags", "+faststart",
            output_path
        ]
        
        await self._execute_merge(cmd, output_path, input_txt_path)
    
    async def _execute_demux_merge(self):
        """Execute concat demux merge for incompatible codecs."""
        # Build complex filter for concatenation
        inputs = []
        filter_complex = []
        
        for i, file in enumerate(self.files):
            inputs.extend(["-i", file.path])
            filter_complex.append(f"[{i}:v:0][{i}:a:0]")
        
        filter_complex_str = "".join(filter_complex) + f"concat=n={len(self.files)}:v=1:a=1[outv][outa]"
        
        output_path = f"{self.dir}/{self.output_name}"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            *inputs,
            "-filter_complex", filter_complex_str,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-c:a", "aac",
            "-metadata", f"title={self.tag}",
            "-movflags", "+faststart",
            output_path
        ]
        
        await self._execute_merge(cmd, output_path)
    
    async def _execute_complex_merge(self):
        """Execute complex merge for mixed media types."""
        # This would handle cases like adding audio to video, picture-in-picture, etc.
        # For now, we'll use a simple concat demux approach as fallback
        await self._execute_demux_merge()
    
    async def _execute_merge(self, cmd: List[str], output_path: str, extra_cleanup: str = None):
        """Execute merge command with proper status tracking and cleanup."""
        from bot.helper.mirror_leech_utils.status_utils.merge_status import MergeStatus
        
        # Setup status tracking
        ffmpeg = FFMpeg(self)
        async with task_dict_lock:
            task_dict[self.mid] = MergeStatus(self, ffmpeg)
        
        # Calculate total duration for progress tracking
        total_duration = sum(f.duration for f in self.files)
        
        # Execute merge
        success = await ffmpeg.execute_merge(cmd, output_path, total_duration)
        
        if not success:
            raise Exception("FFmpeg merge process failed")
        
        if not await aiopath.exists(output_path):
            raise Exception("Output file was not created")
        
        # Cleanup
        cleanup_tasks = []
        for file in self.files:
            cleanup_tasks.append(remove(file.path))
            cleanup_tasks.append(remove(ospath.dirname(file.path)))
        
        if extra_cleanup and await aiopath.exists(extra_cleanup):
            cleanup_tasks.append(remove(extra_cleanup))
        
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        
        # Update final properties
        self.name = self.output_name
        await super().on_download_complete()
    
    async def on_download_error(self, error: str):
        """Handle download errors with session cleanup."""
        user_id = self.message.from_user.id
        if user_id in MERGE_SESSIONS.sessions:
            MERGE_SESSIONS.cleanup_session(user_id)
        await super().on_download_error(error)
    
    async def on_upload_error(self, error: str):
        """Handle upload errors with proper cleanup."""
        try:
            # Cleanup download directory
            if await aiopath.exists(self.dir):
                for root, dirs, files in await sync_to_async(walk, self.dir, topdown=False):
                    for name in files:
                        await remove(ospath.join(root, name))
                    for name in dirs:
                        try:
                            await aiopath.rmdir(ospath.join(root, name))
                        except:
                            pass
                await aiopath.rmdir(self.dir)
        except Exception as e:
            LOGGER.error(f"Error during cleanup: {str(e)}")
        
        await super().on_upload_error(error)


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
    args = message.text.split()[1:] if len(message.text.split()) > 1 else []
    arg_dict = {"-n": "", "-up": "", "-rcf": ""}
    
    if args:
        arg_parser(args, arg_dict)
    
    bot_loop.create_task(Merge(
        client, 
        message, 
        is_session_done=True,
        **arg_dict
    ).new_event())


@new_task
async def merge_cancel(client, message):
    """Cancel active merge session."""
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
    session = MERGE_SESSIONS.get_session(user_id)
    
    if not session:
        return
    
    # Check if message has supported media
    media = message.document or message.video or message.audio
    if not media:
        return
    
    # Add file to session
    success, msg = MERGE_SESSIONS.add_file(user_id, message)
    
    if success:
        status = MERGE_SESSIONS.get_session_status(user_id)
        await send_message(message, status)
    else:
        await send_message(message, "❌ No active merge session to cancel.")


def get_merge_session_info(user_id: int) -> dict | None:
    """Get merge session info for a user."""
    return MERGE_SESSIONS.get_session(user_id)