from asyncio import sleep
from functools import partial
from html import escape
from io import BytesIO
from os import getcwd
from re import findall
from time import time

from aiofiles.os import makedirs, remove
from aiofiles.os import path as aiopath
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler

from bot import (
    auth_chats,
    excluded_extensions,
    included_extensions,
    sudo_users,
    user_data,
)
from bot.core.config_manager import Config
from bot.core.telegram_manager import TgClient
from bot.helper.ext_utils.bot_utils import (
    get_size_bytes,
    new_task,
    update_user_ldata,
)
from bot.helper.ext_utils.db_handler import database
from bot.helper.ext_utils.help_messages import user_settings_text
from bot.helper.ext_utils.media_utils import create_thumb
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_file,
    send_message,
)

handler_dict = {}
no_thumb = "https://i.ibb.co/HD9N8mXt/file-000000001ec861f8b1743e7f048f648f.png"

leech_options = [
    "LEECH_SPLIT_SIZE",
    "THUMBNAIL_LAYOUT",
    "USER_DUMP",
    "USER_SESSION",
]
automation_options = [
    "AUTO_LEECH",
    "AUTO_LEECH_CMD",
    "AUTO_MIRROR",
    "AUTO_MIRROR_CMD",
    "AUTO_ENCODE",
    "AUTO_RESUME",
    "AUTO_COMPRESS_CMD",
]
filename_options = [
    "FILENAME_REPLACE",
    "CLEAN_FILENAME",
    "LEECH_FILENAME_PREFIX",
    "LEECH_FILENAME_SUFFIX",
    "LEECH_FILENAME_CAPTION",
    "AUTO_CAPTION_REPLACE",
    "AUTO_CAPTION_REMOVE",
    "LEECH_CAPTION_FONT",
    "NAME_SUBSTITUTE",
    "AUTO_RENAME_ENABLED",
]
auto_rename_options = [
    "AUTO_RENAME_TEMPLATE",
    "AUTO_RENAME_START_EPISODE",
    "AUTO_RENAME_START_SEASON",
]
rclone_options = ["RCLONE_CONFIG", "RCLONE_PATH", "RCLONE_FLAGS"]
gdrive_options = ["TOKEN_PICKLE", "GDRIVE_ID", "INDEX_URL"]
lulustream_options = ["LULU_API_KEY"]
gofile_options = ["GOFILE_TOKEN", "GOFILE_FOLDER_ID"]
buzzheavier_options = ["BUZZHEAVIER_TOKEN", "BUZZHEAVIER_FOLDER_ID"]
pixeldrain_options = ["PIXELDRAIN_KEY"]
uphoster_options = (
    rclone_options + gdrive_options + gofile_options + buzzheavier_options + pixeldrain_options + lulustream_options
)
ffset_options = ["METADATA", "AUDIO_METADATA", "VIDEO_METADATA", "SUBTITLE_METADATA"]
watermark_options = ["WATERMARK_TEXT", "WATERMARK_POSITION", "WATERMARK_SIZE"]
auto_thumb_options = ["TMDB_API_KEY", "AUTO_THUMBNAIL_FORMAT"]
thumbnail_menu_options = ["THUMBNAIL", "THUMBNAIL_LAYOUT", "AUTO_THUMBNAIL_ENABLED"]


async def get_user_settings(from_user, stype="main"):
    if not from_user:
        return "User not found!", None, None
    user_id = from_user.id
    name = from_user.mention
    buttons = ButtonMaker()
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    thumbpath = f"thumbnails/{user_id}.jpg"
    user_dict = user_data.get(user_id, {})
    thumbnail = thumbpath if await aiopath.exists(thumbpath) else no_thumb

    if stype == "leech":
        buttons.data_button("📦 Split Size", f"userset {user_id} menu LEECH_SPLIT_SIZE")
        buttons.data_button(" User Dump", f"userset {user_id} menu USER_DUMP")
        buttons.data_button("👤 User Session", f"userset {user_id} menu USER_SESSION")
        buttons.data_button("🖼️ Thumbnail", f"userset {user_id} thumbnail_menu")

        if user_dict.get("AS_DOCUMENT", False) or (
            "AS_DOCUMENT" not in user_dict and Config.AS_DOCUMENT
        ):
            ltype = "📄 Document"
            buttons.data_button("📺 Send As Media", f"userset {user_id} tog AS_DOCUMENT f")
        else:
            ltype = "📺 Media"
            buttons.data_button("📄 Send As Document", f"userset {user_id} tog AS_DOCUMENT t")

        if user_dict.get("MEDIA_GROUP", False) or (
            "MEDIA_GROUP" not in user_dict and Config.MEDIA_GROUP
        ):
            buttons.data_button("🚫 Disable Group", f"userset {user_id} tog MEDIA_GROUP f")
            media_group = "✅ Enabled"
        else:
            buttons.data_button("✅ Enable Group", f"userset {user_id} tog MEDIA_GROUP t")
            media_group = "❌ Disabled"

        bot_pm_enabled = user_dict.get("BOT_PM", Config.BOT_PM if hasattr(Config, "BOT_PM") else False)
        if bot_pm_enabled:
            buttons.data_button("📩 Disable PM", f"userset {user_id} tog BOT_PM f")
            bot_pm_status = "✅ Enabled"
        else:
            buttons.data_button("📩 Enable PM", f"userset {user_id} tog BOT_PM t")
            bot_pm_status = "❌ Disabled"

        buttons.data_button("🔙 Back", f"userset {user_id} back")
        buttons.data_button("❌ Close", f"userset {user_id} close")

        udump = user_dict.get("USER_DUMP", "None")
        usess = "✅ Added" if user_dict.get("USER_SESSION", False) else "❌ None"
        lsplit = user_dict.get("LEECH_SPLIT_SIZE", Config.LEECH_SPLIT_SIZE or "Default")

        text = f"""<blockquote>
╭⚙️ <b>Leech Settings</b>
┊📦 <b>Format:</b> <code>{ltype}</code>
┊🚀 <b>Split Size:</b> <code>{lsplit}</code>
┊📸 <b>Media Group:</b> <code>{media_group}</code>
┊👤 <b>User Session:</b> <code>{usess}</code>
┊📦 <b>User Dump:</b> <code>{udump}</code>
╰📩 <b>Bot PM:</b> <code>{bot_pm_status}</code>
</blockquote>"""
    elif stype == "rclone":
        buttons.data_button("📁 Config", f"userset {user_id} menu RCLONE_CONFIG")
        buttons.data_button("📂 Path", f"userset {user_id} menu RCLONE_PATH")
        buttons.data_button("🚩 Flags", f"userset {user_id} menu RCLONE_FLAGS")
        buttons.data_button("🔙 Back", f"userset {user_id} uphoster")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        rccmsg = "✅ Exists" if await aiopath.exists(rclone_conf) else "❌ Not Exists"
        rccpath = user_dict.get("RCLONE_PATH", Config.RCLONE_PATH or "None")
        rcflags = user_dict.get("RCLONE_FLAGS", Config.RCLONE_FLAGS or "None")
        text = f"""<blockquote>
╭⚙️ <b>Rclone Settings</b>
┊📁 <b>Config:</b> <code>{rccmsg}</code>
┊📂 <b>Path:</b> <code>{rccpath}</code>
╰🚩 <b>Flags:</b> <code>{rcflags}</code>
</blockquote>"""
    elif stype == "gdrive":
        buttons.data_button("🔑 token.pickle", f"userset {user_id} menu TOKEN_PICKLE")
        buttons.data_button("💾 Gdrive ID", f"userset {user_id} menu GDRIVE_ID")
        buttons.data_button("🔗 Index URL", f"userset {user_id} menu INDEX_URL")
        if user_dict.get("STOP_DUPLICATE", Config.STOP_DUPLICATE):
            buttons.data_button("🚫 Disable Duplicate", f"userset {user_id} tog STOP_DUPLICATE f")
            sd_msg = "✅ Enabled"
        else:
            buttons.data_button("✅ Enable Duplicate", f"userset {user_id} tog STOP_DUPLICATE t")
            sd_msg = "❌ Disabled"
        buttons.data_button("🔙 Back", f"userset {user_id} uphoster")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        tokenmsg = "✅ Exists" if await aiopath.exists(token_pickle) else "❌ Not Exists"
        gdrive_id = user_dict.get("GDRIVE_ID", Config.GDRIVE_ID or "None")
        index = user_dict.get("INDEX_URL", "None")
        text = f"""<blockquote>
╭⚙️ <b>Gdrive Settings</b>
┊🔑 <b>Token:</b> <code>{tokenmsg}</code>
┊💾 <b>Gdrive ID:</b> <code>{gdrive_id}</code>
┊🔗 <b>Index URL:</b> <code>{index}</code>
╰🔄 <b>Stop Duplicate:</b> <code>{sd_msg}</code>
</blockquote>"""
    elif stype == "upload_dest":
        buttons.data_button("☁️ Gdrive", f"userset {user_id} set_upload gd")
        buttons.data_button("📁 Rclone", f"userset {user_id} set_upload rc")
        buttons.data_button("🎥 YouTube", f"userset {user_id} set_upload yt")
        buttons.data_button("📂 Gofile", f"userset {user_id} set_upload go")
        buttons.data_button("💾 Buzzheavier", f"userset {user_id} set_upload biz")
        buttons.data_button("💧 Pixeldrain", f"userset {user_id} set_upload pix")
        buttons.data_button("🎞️ LuluStream", f"userset {user_id} set_upload lulu")
        buttons.data_button("🔙 Back", f"userset {user_id} back")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        text = f"""<blockquote>
╭📤 <b>Upload Destination Settings for {name}</b>
╰Choose where to upload your files.
</blockquote>"""
    elif stype == "youtube":
        buttons.data_button("🔒 Privacy", f"userset {user_id} menu YT_DEFAULT_PRIVACY")
        buttons.data_button("📂 Category", f"userset {user_id} menu YT_DEFAULT_CATEGORY")
        buttons.data_button("🏷️ Tags", f"userset {user_id} menu YT_DEFAULT_TAGS")
        buttons.data_button("📝 Description", f"userset {user_id} menu YT_DEFAULT_DESCRIPTION")
        buttons.data_button("📁 Folder Mode", f"userset {user_id} menu YT_DEFAULT_FOLDER_MODE")
        buttons.data_button("📋 Playlist ID", f"userset {user_id} menu YT_ADD_TO_PLAYLIST_ID")
        buttons.data_button("🔙 Back", f"userset {user_id} back")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        yt_privacy = user_dict.get("YT_DEFAULT_PRIVACY", "unlisted")
        yt_category = user_dict.get("YT_DEFAULT_CATEGORY", "22")
        yt_tags = user_dict.get("YT_DEFAULT_TAGS", "None")
        yt_description = user_dict.get("YT_DEFAULT_DESCRIPTION", "Uploaded by TellY-MLTB.")
        yt_folder_mode = user_dict.get("YT_DEFAULT_FOLDER_MODE", "playlist")
        yt_add_to_playlist_id = user_dict.get("YT_ADD_TO_PLAYLIST_ID", "None")
        text = f"""<blockquote>
╭🎥 <b>YouTube Settings</b>
┊🔒 <b>Privacy:</b> <code>{yt_privacy}</code>
┊📂 <b>Category:</b> <code>{yt_category}</code>
┊🏷️ <b>Tags:</b> <code>{yt_tags}</code>
┊📝 <b>Description:</b> <code>{yt_description}</code>
┊📁 <b>Folder Mode:</b> <code>{yt_folder_mode.capitalize()}</code>
╰📋 <b>Playlist ID:</b> <code>{yt_add_to_playlist_id}</code>
</blockquote>"""
    elif stype == "youtube_folder_mode_menu":
        buttons.data_button("📋 Playlist", f"userset {user_id} set_yt_folder_mode playlist")
        buttons.data_button("📄 Individual", f"userset {user_id} set_yt_folder_mode individual")
        buttons.data_button("🔙 Back", f"userset {user_id} youtube")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        text = f"""<blockquote>
╭📁 <b>YouTube Folder Mode</b>
╰Choose how to handle folder uploads.
</blockquote>"""
    elif stype == "lulustream":
        buttons.data_button("🔑 API Key", f"userset {user_id} menu LULU_API_KEY")
        buttons.data_button("🔙 Back", f"userset {user_id} uphoster")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        lulu_api = user_dict.get("LULU_API_KEY", Config.LULU_API_KEY or "None")
        text = f"""<blockquote>
╭⚙️ <b>LuluStream Settings</b>
╰🔑 <b>API Key:</b> <code>{lulu_api}</code>
</blockquote>"""
    elif stype == "uphoster":
        buttons.data_button("📁 Rclone", f"userset {user_id} rclone")
        buttons.data_button("☁️ Gdrive API", f"userset {user_id} gdrive")
        buttons.data_button("🔑 Pixeldrain", f"userset {user_id} menu PIXELDRAIN_KEY")
        buttons.data_button("🔑 Buzz Token", f"userset {user_id} menu BUZZHEAVIER_TOKEN")
        buttons.data_button("💾 Buzz Folder", f"userset {user_id} menu BUZZHEAVIER_FOLDER_ID")
        buttons.data_button("🔑 GoFile Token", f"userset {user_id} menu GOFILE_TOKEN")
        buttons.data_button("💾 GoFile Folder", f"userset {user_id} menu GOFILE_FOLDER_ID")
        buttons.data_button("🎞️ LuluStream", f"userset {user_id} lulustream")
        buttons.data_button("🔙 Back", f"userset {user_id} back")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        pdk = user_dict.get("PIXELDRAIN_KEY", Config.PIXELDRAIN_KEY or "None")
        bht = user_dict.get("BUZZHEAVIER_TOKEN", Config.BUZZHEAVIER_TOKEN or "None")
        bhf = user_dict.get("BUZZHEAVIER_FOLDER_ID", Config.BUZZHEAVIER_FOLDER_ID or "None")
        gft = user_dict.get("GOFILE_TOKEN", Config.GOFILE_API or "None")
        gff = user_dict.get("GOFILE_FOLDER_ID", Config.GOFILE_FOLDER_ID or "None")
        lulu_api = user_dict.get("LULU_API_KEY", Config.LULU_API_KEY or "None")
        text = f"""<blockquote>
╭⚙️ <b>Upload Hoster Settings</b>
┊🔑 <b>Pixeldrain:</b> <code>{pdk}</code>
┊🔑 <b>Buzzheavier:</b> <code>{bht}</code>
┊💾 <b>Buzz Folder:</b> <code>{bhf}</code>
┊🔑 <b>GoFile Token:</b> <code>{gft}</code>
┊💾 <b>GoFile Folder:</b> <code>{gff}</code>
╰🎞️ <b>LuluStream:</b> <code>{lulu_api}</code>
</blockquote>"""
    elif stype == "ffset":
        buttons.data_button("📋 Metadata", f"userset {user_id} menu METADATA")
        buttons.data_button("🔊 Audio Meta", f"userset {user_id} menu AUDIO_METADATA")
        buttons.data_button("🎞️ Video Meta", f"userset {user_id} menu VIDEO_METADATA")
        buttons.data_button("📜 Sub Meta", f"userset {user_id} menu SUBTITLE_METADATA")
        buttons.data_button(" Back", f"userset {user_id} back")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        mdt = user_dict.get("METADATA", Config.METADATA or "None")
        amdt = user_dict.get("AUDIO_METADATA", Config.AUDIO_METADATA or "None")
        vmdt = user_dict.get("VIDEO_METADATA", Config.VIDEO_METADATA or "None")
        smdt = user_dict.get("SUBTITLE_METADATA", Config.SUBTITLE_METADATA or "None")
        text = f"""<blockquote>
╭⚙️ <b>Metadata Settings</b>
┊📋 <b>Metadata:</b> <code>{mdt}</code>
┊🔊 <b>Audio Meta:</b> <code>{amdt}</code>
┊🎞️ <b>Video Meta:</b> <code>{vmdt}</code>
╰📜 <b>Subtitle Meta:</b> <code>{smdt}</code>
</blockquote>"""
    elif stype == "watermark":
        buttons.data_button("📝 Text", f"userset {user_id} menu WATERMARK_TEXT")
        buttons.data_button("📍 Position", f"userset {user_id} menu WATERMARK_POSITION")
        buttons.data_button("📏 Size", f"userset {user_id} menu WATERMARK_SIZE")
        buttons.data_button("🖼️ Upload Image", f"userset {user_id} file WATERMARK_IMAGE")
        buttons.data_button("🔙 Back", f"userset {user_id} back")
        buttons.data_button("❌ Close", f"userset {user_id} close")

        w_text = user_dict.get("WATERMARK_TEXT") or user_dict.get("WATERMARK_KEY") or Config.WATERMARK_KEY or "None"
        w_pos = user_dict.get("WATERMARK_POSITION", "Top-Left")
        w_size = user_dict.get("WATERMARK_SIZE", "20")
        w_image_status = "✅ Set" if await aiopath.exists(f"watermarks/{user_id}.png") else "❌ Not Set"

        text = f"""<blockquote>
╭💧 <b>Watermark Settings</b>
┊📝 <b>Text:</b> <code>{escape(w_text)}</code>
┊📍 <b>Position:</b> <code>{w_pos}</code>
┊📏 <b>Size:</b> <code>{w_size}</code>
╰🖼️ <b>Image:</b> <code>{w_image_status}</code>
</blockquote>"""
    elif stype == "thumbnail_menu":
        buttons.data_button("📤 Upload Thumbnail", f"userset {user_id} menu THUMBNAIL")
        buttons.data_button("🖼️ Auto Thumbnail", f"userset {user_id} auto_thumb")
        buttons.data_button("🎨 Thumbnail Layout", f"userset {user_id} menu THUMBNAIL_LAYOUT")

        # Check auto thumbnail status
        auto_thumb_enabled = user_dict.get("AUTO_THUMBNAIL_ENABLED", Config.AUTO_THUMBNAIL_ENABLED if hasattr(Config, 'AUTO_THUMBNAIL_ENABLED') else False)
        buttons.data_button(f"✅ Enabled" if auto_thumb_enabled else "❌ Disabled", f"userset {user_id} tog AUTO_THUMBNAIL_ENABLED {'f' if auto_thumb_enabled else 't'}")

        buttons.data_button("🔙 Back", f"userset {user_id} leech")
        buttons.data_button("❌ Close", f"userset {user_id} close")

        # Check if manual thumbnail exists
        thumb_path = f"thumbnails/{user_id}.jpg"
        thumb_status = "✅ Set" if await aiopath.exists(thumb_path) else "❌ Not Set"

        # Check auto thumbnail status
        auto_thumb_enabled = user_dict.get("AUTO_THUMBNAIL_ENABLED", Config.AUTO_THUMBNAIL_ENABLED if hasattr(Config, 'AUTO_THUMBNAIL_ENABLED') else False)
        auto_thumb_status = "✅ Enabled" if auto_thumb_enabled else "❌ Disabled"

        # Thumbnail layout
        thumb_layout = user_dict.get("THUMBNAIL_LAYOUT", Config.THUMBNAIL_LAYOUT or "None")

        text = f"""<blockquote>
╭🖼️ <b>Thumbnail Settings</b>
┊📤 <b>Manual Thumbnail:</b> <code>{thumb_status}</code>
┊🖼️ <b>Auto Thumbnail:</b> <code>{auto_thumb_status}</code>
╰🎨 <b>Layout:</b> <code>{thumb_layout}</code>
</blockquote>"""
    elif stype == "auto_thumb":
        buttons.data_button("🔑 TMDB API Key", f"userset {user_id} menu TMDB_API_KEY")
        buttons.data_button("🖼️ Format", f"userset {user_id} auto_thumb_format_menu")
        buttons.data_button("🎬 TMDB Source", f"userset {user_id} tog TMDB_ENABLED {'f' if user_dict.get('TMDB_ENABLED', Config.TMDB_ENABLED if hasattr(Config, 'TMDB_ENABLED') else True) else 't'}")
        buttons.data_button("📽️ IMDB Source", f"userset {user_id} tog IMDB_ENABLED {'f' if user_dict.get('IMDB_ENABLED', Config.IMDB_ENABLED if hasattr(Config, 'IMDB_ENABLED') else True) else 't'}")
        buttons.data_button("🔙 Back", f"userset {user_id} thumbnail_menu")
        buttons.data_button("❌ Close", f"userset {user_id} close")

        tmdb_key = user_dict.get("TMDB_API_KEY", Config.TMDB_API_KEY if hasattr(Config, 'TMDB_API_KEY') else "")
        tmdb_key_status = "✅ Set" if tmdb_key else "❌ Not Set"
        thumb_format = user_dict.get("AUTO_THUMBNAIL_FORMAT", Config.AUTO_THUMBNAIL_FORMAT if hasattr(Config, 'AUTO_THUMBNAIL_FORMAT') else "poster")
        thumb_format_display = "🖼️ Poster" if thumb_format == "poster" else "🎞️ Backdrop"
        tmdb_enabled = "✅ Enabled" if user_dict.get("TMDB_ENABLED", Config.TMDB_ENABLED if hasattr(Config, 'TMDB_ENABLED') else True) else "❌ Disabled"
        imdb_enabled = "✅ Enabled" if user_dict.get("IMDB_ENABLED", Config.IMDB_ENABLED if hasattr(Config, 'IMDB_ENABLED') else True) else "❌ Disabled"

        text = f"""<blockquote>
╭🖼️ <b>Auto Thumbnail Settings</b>
┊🔑 <b>TMDB API Key:</b> <code>{tmdb_key_status}</code>
┊🖼️ <b>Format:</b> <code>{thumb_format_display}</code>
┊🎬 <b>TMDB Source:</b> <code>{tmdb_enabled}</code>
╰📽️ <b>IMDB Source:</b> <code>{imdb_enabled}</code>
</blockquote>"""
    elif stype == "auto_thumb_format_menu":
        buttons.data_button("🖼️ Poster", f"userset {user_id} set_thumb_format poster")
        buttons.data_button("🎞️ Backdrop", f"userset {user_id} set_thumb_format backdrop")
        buttons.data_button("🔙 Back", f"userset {user_id} auto_thumb")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        text = f"""<blockquote>
╭🖼️ <b>Thumbnail Format Selection</b>
┊Select thumbnail format for auto thumbnails:
┊
┊🖼️ <b>Poster</b> - Movie/TV show poster
╰🎞️ <b>Backdrop</b> - Background/scene image
</blockquote>"""
    elif stype == "automation":
        buttons.data_button("🚀 Auto Leech", f"userset {user_id} tog AUTO_LEECH {'f' if user_dict.get('AUTO_LEECH') else 't'}")
        buttons.data_button("🚀 Auto Mirror", f"userset {user_id} tog AUTO_MIRROR {'f' if user_dict.get('AUTO_MIRROR') else 't'}")
        buttons.data_button("🚀 Auto Encode", f"userset {user_id} tog AUTO_ENCODE {'f' if user_dict.get('AUTO_ENCODE') else 't'}")
        buttons.data_button("🚀 Auto Resume", f"userset {user_id} tog AUTO_RESUME {'f' if user_dict.get('AUTO_RESUME') else 't'}")
        buttons.data_button("🎬 Leech Cmd", f"userset {user_id} menu AUTO_LEECH_CMD")
        buttons.data_button("🎬 Mirror Cmd", f"userset {user_id} menu AUTO_MIRROR_CMD")
        buttons.data_button("🎬 Compress Cmd", f"userset {user_id} menu AUTO_COMPRESS_CMD")
        buttons.data_button("🔙 Back", f"userset {user_id} back")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        aleech = "✅ Enabled" if user_dict.get("AUTO_LEECH") else "❌ Disabled"
        amirror = "✅ Enabled" if user_dict.get("AUTO_MIRROR") else "❌ Disabled"
        aencode = "✅ Enabled" if user_dict.get("AUTO_ENCODE") else "❌ Disabled"
        aresume = "✅ Enabled" if user_dict.get("AUTO_RESUME") else "❌ Disabled"
        aleech_cmd = user_dict.get("AUTO_LEECH_CMD") or "None"
        amirror_cmd = user_dict.get("AUTO_MIRROR_CMD") or "None"
        ac_cmd = user_dict.get("AUTO_COMPRESS_CMD") or "None"
        text = f"""<blockquote>
╭🤖 <b>Auto Features Settings</b>
┊🚀 <b>Auto Leech:</b> <code>{aleech}</code>
┊🎬 <b>Leech Cmd:</b> <code>{escape(aleech_cmd)}</code>
┊🚀 <b>Auto Mirror:</b> <code>{amirror}</code>
┊🎬 <b>Mirror Cmd:</b> <code>{escape(amirror_cmd)}</code>
┊🚀 <b>Auto Encode:</b> <code>{aencode}</code>
┊🚀 <b>Auto Resume:</b> <code>{aresume}</code>
╰🎬 <b>Compress Cmd:</b> <code>{escape(ac_cmd)}</code>
</blockquote>"""
    elif stype == "filename":
        buttons.data_button("🔄 Auto Rename", f"userset {user_id} tog AUTO_RENAME_ENABLED {'f' if user_dict.get('AUTO_RENAME_ENABLED') else 't'}")
        buttons.data_button("📋 Rename Template", f"userset {user_id} menu AUTO_RENAME_TEMPLATE")
        buttons.data_button("1️⃣ Start Episode", f"userset {user_id} menu AUTO_RENAME_START_EPISODE")
        buttons.data_button("📺 Start Season", f"userset {user_id} menu AUTO_RENAME_START_SEASON")
        buttons.data_button("✏️ Fn Replace", f"userset {user_id} menu FILENAME_REPLACE")
        buttons.data_button("🧹 Clean Fn", f"userset {user_id} tog CLEAN_FILENAME {'f' if user_dict.get('CLEAN_FILENAME') else 't'}")
        buttons.data_button("📝 Prefix", f"userset {user_id} menu LEECH_FILENAME_PREFIX")
        buttons.data_button("📝 Suffix", f"userset {user_id} menu LEECH_FILENAME_SUFFIX")
        buttons.data_button("💬 Caption", f"userset {user_id} menu LEECH_FILENAME_CAPTION")
        buttons.data_button("📝 Cap Replace", f"userset {user_id} menu AUTO_CAPTION_REPLACE")
        buttons.data_button("🧹 Cap Remove", f"userset {user_id} menu AUTO_CAPTION_REMOVE")
        buttons.data_button(
            "Included Extensions", f"userset {user_id} menu INCLUDED_EXTENSIONS"
        )
        if user_dict.get("INCLUDED_EXTENSIONS", False):
            inc_ex = user_dict["INCLUDED_EXTENSIONS"]
        elif "INCLUDED_EXTENSIONS" not in user_dict:
            inc_ex = included_extensions
        else:
            inc_ex = "None"
        if user_dict.get("NAME_SUBSTITUTE", False) or (
            "NAME_SUBSTITUTE" not in user_dict and Config.NAME_SUBSTITUTE
        ):
            ns_msg = "Added"
        else:
            ns_msg = "None"
        buttons.data_button(
            "✏️ Substitute",
            f"userset {user_id} menu NAME_SUBSTITUTE",
        )
        buttons.data_button("🔡 Leech Font", f"userset {user_id} menu LEECH_CAPTION_FONT")
        buttons.data_button("🔙 Back", f"userset {user_id} back")
        buttons.data_button("❌ Close", f"userset {user_id} close")

        # Auto Rename settings
        auto_rename = "✅ Enabled" if user_dict.get("AUTO_RENAME_ENABLED", Config.AUTO_RENAME_ENABLED) else "❌ Disabled"
        rename_template = user_dict.get("AUTO_RENAME_TEMPLATE", Config.AUTO_RENAME_TEMPLATE or "{title} S{season}E{episode} {quality}")
        start_episode = user_dict.get("AUTO_RENAME_START_EPISODE", Config.AUTO_RENAME_START_SEASON or "1")
        start_season = user_dict.get("AUTO_RENAME_START_SEASON", Config.AUTO_RENAME_START_SEASON or "1")

        fn_rep = user_dict.get("FILENAME_REPLACE", Config.FILENAME_REPLACE or "None")
        clean_file = "✅ Enabled" if user_dict.get("CLEAN_FILENAME", Config.CLEAN_FILENAME) else "❌ Disabled"
        lprefix = user_dict.get("LEECH_FILENAME_PREFIX", Config.LEECH_FILENAME_PREFIX or "None")
        lsuffix = user_dict.get("LEECH_FILENAME_SUFFIX", Config.LEECH_FILENAME_SUFFIX or "None")
        lcap = user_dict.get("LEECH_FILENAME_CAPTION", Config.LEECH_FILENAME_CAPTION or "None")
        ac_rep = user_dict.get("AUTO_CAPTION_REPLACE", Config.AUTO_CAPTION_REPLACE or "None")
        ac_rem = user_dict.get("AUTO_CAPTION_REMOVE", Config.AUTO_CAPTION_REMOVE or "None")
        # ns_msg is calculated above now
        lfont = user_dict.get("LEECH_CAPTION_FONT", Config.LEECH_CAPTION_FONT or "None")

        text = f"""<blockquote>
╭📝 <b>Filename Options</b>
┊🔄 <b>Auto Rename:</b> <code>{auto_rename}</code>
┊📋 <b>Rename Template:</b> <code>{escape(rename_template)}</code>
┊1️⃣ <b>Start Episode:</b> <code>{start_episode}</code>
┊📺 <b>Start Season:</b> <code>{start_season}</code>
┊✏️ <b>Fn Replace:</b> <code>{escape(fn_rep)}</code>
┊🧹 <b>Clean Fn:</b> <code>{clean_file}</code>
┊📝 <b>Prefix:</b> <code>{escape(lprefix)}</code>
┊📝 <b>Suffix:</b> <code>{escape(lsuffix)}</code>
┊💬 <b>Caption:</b> <code>{escape(lcap)}</code>
┊📝 <b>Cap Replace:</b> <code>{escape(ac_rep)}</code>
┊🧹 <b>Cap Remove:</b> <code>{escape(ac_rem)}</code>
┊✏️ <b>Substitute:</b> <code>{ns_msg}</code>
╰🔡 <b>Leech Font:</b> <code>{escape(lfont)}</code>
</blockquote>"""
    else:
        buttons.data_button("📥 Leech", f"userset {user_id} leech")
        buttons.data_button("🎥 YouTube", f"userset {user_id} youtube")
        buttons.data_button("☁️ Upload Hosters", f"userset {user_id} uphoster")
        buttons.data_button("🎬 Metadata Set", f"userset {user_id} ffset")
        buttons.data_button("🤖 Auto Features", f"userset {user_id} automation")
        buttons.data_button("📝 Fn Options", f"userset {user_id} filename")
        buttons.data_button("📤 Upload Paths", f"userset {user_id} menu UPLOAD_PATHS")
        buttons.data_button("🚫 Excluded Ext", f"userset {user_id} menu EXCLUDED_EXTENSIONS")
        buttons.data_button("💧 Watermark", f"userset {user_id} watermark")
        buttons.data_button("🎞️ FFmpeg Cmds", f"userset {user_id} menu FFMPEG_CMDS")
        buttons.data_button("⬇️ YT-DLP Options", f"userset {user_id} menu YT_DLP_OPTIONS")

        default_upload = user_dict.get("DEFAULT_UPLOAD", Config.DEFAULT_UPLOAD or "gd")
        if default_upload == "gd":
            du = "☁️ Gdrive API"
        elif default_upload == "rc":
            du = "📁 Rclone"
        elif default_upload == "yt":
            du = "🎥 YouTube"
        elif default_upload == "go":
            du = "📂 Gofile"
        elif default_upload == "biz":
            du = "💾 Buzzheavier"
        elif default_upload == "pix":
            du = "💧 Pixeldrain"
        elif default_upload == "lulu":
            du = "🎞️ LuluStream"
        else:
            du = "☁️ Gdrive API"

        buttons.data_button(f"📤 Default: {default_upload.upper()}", f"userset {user_id} upload_dest")

        user_tokens = user_dict.get("USER_TOKENS", False)
        tr = "👤 My" if user_tokens else "👑 Owner"
        trr = "👑 Owner" if user_tokens else "👤 My"
        buttons.data_button(f"🔄 Use {trr} Token", f"userset {user_id} tog USER_TOKENS {'f' if user_tokens else 't'}")

        if user_dict:
            buttons.data_button("Reset All", f"userset {user_id} reset all")
        buttons.data_button("❌ Close", f"userset {user_id} close")

        aleech = "✅ Enabled" if user_dict.get("AUTO_LEECH", Config.AUTO_LEECH) else "❌ Disabled"
        up_paths = user_dict.get("UPLOAD_PATHS", Config.UPLOAD_PATHS or "None")
        ex_ex = user_dict.get("EXCLUDED_EXTENSIONS", excluded_extensions or "None")
        ytopt = user_dict.get("YT_DLP_OPTIONS", Config.YT_DLP_OPTIONS or "None")

        if user_dict.get("NAME_SUBSTITUTE", False) or (
            "NAME_SUBSTITUTE" not in user_dict and Config.NAME_SUBSTITUTE
        ):
            ns_msg = "✅ Added"
        else:
            ns_msg = "❌ None"

        if user_dict.get("LEECH_FILENAME_PREFIX", False) or (
            "LEECH_FILENAME_PREFIX" not in user_dict and Config.LEECH_FILENAME_PREFIX
        ):
            np_msg = "✅ Added"
        else:
            np_msg = "❌ None"

        if user_dict.get("INCLUDED_EXTENSIONS", False):
            inc_ex = user_dict["INCLUDED_EXTENSIONS"]
        elif "INCLUDED_EXTENSIONS" not in user_dict:
            inc_ex = included_extensions
        else:
            inc_ex = "None"

        text = f"""<blockquote>
╭⚙️ <b>Settings</b>
┊📦 <b>Package:</b> <code>{du}</code>
┊🚀 <b>Auto Leech:</b> <code>{aleech}</code>
┊🔑 <b>Token:</b> <code>{tr} Config</code>
┊✏️ <b>Name Substitute:</b> <code>{ns_msg}</code>
┊📝 <b>Name Prefix:</b> <code>{np_msg}</code>
┊📤 <b>Paths:</b> <code>{up_paths}</code>
┊🚫 <b>Excl Ext:</b> <code>{ex_ex}</code>
┊✅ <b>Incl Ext:</b> <code>{inc_ex}</code>
╰⬇️ <b>YT-DLP:</b> <code>{ytopt}</code>
</blockquote>"""

    return text, buttons.build_menu(2), thumbnail


async def update_user_settings(query, stype="main"):
    handler_dict[query.from_user.id] = False
    msg, button, t = await get_user_settings(query.from_user, stype)
    await edit_message(query.message, msg, button, t)


@new_task
async def send_user_settings(_, message):
    from_user = message.from_user
    handler_dict[from_user.id] = False
    msg, button, t = await get_user_settings(from_user)
    await send_message(message, msg, button, t)


@new_task
async def add_file(_, message, ftype):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    if ftype == "THUMBNAIL":
        des_dir = await create_thumb(message, user_id)
    elif ftype == "RCLONE_CONFIG":
        rpath = f"{getcwd()}/rclone/"
        await makedirs(rpath, exist_ok=True)
        des_dir = f"{rpath}{user_id}.conf"
        await message.download(file_name=des_dir)
    elif ftype == "TOKEN_PICKLE":
        tpath = f"{getcwd()}/tokens/"
        await makedirs(tpath, exist_ok=True)
        des_dir = f"{tpath}{user_id}.pickle"
        await message.download(file_name=des_dir)  # TODO user font
    elif ftype == "WATERMARK_IMAGE":
        wpath = f"watermarks/"
        await makedirs(wpath, exist_ok=True)
        des_dir = f"{wpath}{user_id}.png"
        await message.download(file_name=des_dir)
    update_user_ldata(user_id, ftype, des_dir)
    await delete_message(message)
    await database.update_user_doc(user_id, ftype, des_dir)


@new_task
async def add_one(_, message, option):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    value = message.text
    if value.startswith("{") and value.endswith("}"):
        try:
            value = eval(value)
            if user_dict.get(option): # Use .get() to safely check if option exists and is not None
                user_dict[option].update(value)
            else:
                update_user_ldata(user_id, option, value)
        except Exception as e:
            await send_message(message, f"❌ Error: {e!s}")
            return
    else:
        await send_message(message, "❌ It must be dict!")
        return
    await delete_message(message)
    await database.update_user_data(user_id)


@new_task
async def remove_one(_, message, option):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    names = message.text.split("/")
    for name in names:
        if name in user_dict[option]:
            del user_dict[option][name]
    await delete_message(message)
    await database.update_user_data(user_id)


@new_task
async def set_option(_, message, option):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    value = message.text
    if option == "LEECH_SPLIT_SIZE":
        if not value.isdigit():
            value = get_size_bytes(value)
        value = min(int(value), TgClient.MAX_SPLIT_SIZE)
    elif option == "EXCLUDED_EXTENSIONS":
        fx = value.split()
        value = ["aria2", "!qB"]
        for x in fx:
            x = x.lstrip(".")
            value.append(x.strip().lower())
    elif option == "INCLUDED_EXTENSIONS":
        fx = value.split()
        value = []
        for x in fx:
            x = x.lstrip(".")
            value.append(x.strip().lower())
    elif option in ["UPLOAD_PATHS", "FFMPEG_CMDS", "YT_DLP_OPTIONS"]:
        if value.startswith("{") and value.endswith("}"):
            try:
                value = eval(value)
            except Exception as e:
                await send_message(message, f"❌ Error: {e!s}")
                return
        else:
            await send_message(message, "❌ It must be dict!")
            return
    update_user_ldata(user_id, option, value)
    await delete_message(message)
    await database.update_user_data(user_id)


async def get_menu(option, message, user_id):
    handler_dict[user_id] = False
    user_dict = user_data.get(user_id, {})
    buttons = ButtonMaker()
    if option in ["THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE"]:
        key = "file"
    else:
        key = "set"
    buttons.data_button("✏️ Set", f"userset {user_id} {key} {option}")
    if option in user_dict and key != "file":
        buttons.data_button("🔄 Reset", f"userset {user_id} reset {option}")
    buttons.data_button("🗑️ Remove", f"userset {user_id} remove {option}")
    if option == "FFMPEG_CMDS":
        ffc = None
        if user_dict.get("FFMPEG_CMDS", False):
            ffc = user_dict["FFMPEG_CMDS"]
            buttons.data_button("➕ Add one", f"userset {user_id} addone {option}")
            buttons.data_button("➖ Remove one", f"userset {user_id} rmone {option}")
        elif "FFMPEG_CMDS" not in user_dict and Config.FFMPEG_CMDS:
            ffc = Config.FFMPEG_CMDS
        if ffc:
            buttons.data_button("📊 FFMPEG VARIABLES", f"userset {user_id} ffvar")
            buttons.data_button("👁️ View", f"userset {user_id} view {option}")
    elif user_dict.get(option):
        if option == "THUMBNAIL":
            buttons.data_button("👁️ View", f"userset {user_id} view {option}")
        elif option in ["YT_DLP_OPTIONS", "UPLOAD_PATHS", "INCLUDED_EXTENSIONS", "EXCLUDED_EXTENSIONS"]:
            buttons.data_button("➕ Add one", f"userset {user_id} addone {option}")
            buttons.data_button("➖ Remove one", f"userset {user_id} rmone {option}")
    if option in leech_options:
        back_to = "leech"
    elif option in automation_options:
        back_to = "automation"
    elif option in filename_options or option in auto_rename_options:
        back_to = "filename"
    elif option in rclone_options:
        back_to = "rclone"
    elif option in gdrive_options:
        back_to = "gdrive"
    elif option in lulustream_options:
        back_to = "lulustream"
    elif option in uphoster_options:
        back_to = "uphoster"
    elif option in ffset_options:
        back_to = "ffset"
    elif option in watermark_options:
        back_to = "watermark"
    elif option in auto_thumb_options:
        back_to = "auto_thumb"
    elif option in thumbnail_menu_options:
        back_to = "thumbnail_menu"
    elif option in [
        "YT_DEFAULT_PRIVACY",
        "YT_DEFAULT_CATEGORY",
        "YT_DEFAULT_TAGS",
        "YT_DEFAULT_DESCRIPTION",
        "YT_ADD_TO_PLAYLIST_ID",
    ]:
        back_to = "youtube"
    else:
        back_to = "back"
    buttons.data_button("🔙 Back", f"userset {user_id} {back_to}")
    buttons.data_button("❌ Close", f"userset {user_id} close")
    text = f"⚙️ Edit menu for: <b>{option}</b>"
    await edit_message(message, text, buttons.build_menu(2))


async def set_ffmpeg_variable(_, message, key, value, index):
    user_id = message.from_user.id
    handler_dict[user_id] = False
    txt = message.text
    user_dict = user_data.setdefault(user_id, {})
    ffvar_data = user_dict.setdefault("FFMPEG_VARIABLES", {})
    ffvar_data = ffvar_data.setdefault(key, {})
    ffvar_data = ffvar_data.setdefault(index, {})
    ffvar_data[value] = txt
    await delete_message(message)
    await database.update_user_data(user_id)


async def ffmpeg_variables(
    client, query, message, user_id, key=None, value=None, index=None
):
    user_dict = user_data.get(user_id, {})
    ffc = None
    if user_dict.get("FFMPEG_CMDS", False):
        ffc = user_dict["FFMPEG_CMDS"]
    elif "FFMPEG_CMDS" not in user_dict and Config.FFMPEG_CMDS:
        ffc = Config.FFMPEG_CMDS
    if ffc:
        buttons = ButtonMaker()
        if key is None:
            msg = "🔑 Choose which key you want to fill/edit variables in it:"
            for k, v in list(ffc.items()):
                add = False
                for i in v:
                    if variables := findall(r"\{(.*?)\}", i):
                        add = True
                if add:
                    buttons.data_button(k, f"userset {user_id} ffvar {k}")
            buttons.data_button("🔙 Back", f"userset {user_id} menu FFMPEG_CMDS")
            buttons.data_button("❌ Close", f"userset {user_id} close")
        elif key in ffc and value is None:
            msg = f"📝 Choose which variable you want to fill/edit: <u>{key}</u>\n\n<b>CMDS:</b>\n{ffc[key]}"
            for ind, vl in enumerate(ffc[key]):
                if variables := set(findall(r"\{(.*?)\}", vl)):
                    for var in variables:
                        buttons.data_button(
                            var, f"userset {user_id} ffvar {key} {var} {ind}"
                        )
            buttons.data_button(
                "🔄 Reset", f"userset {user_id} ffvar {key} ffmpegvarreset"
            )
            buttons.data_button("🔙 Back", f"userset {user_id} ffvar")
            buttons.data_button("❌ Close", f"userset {user_id} close")
        elif key in ffc and value:
            old_value = (
                user_dict.get("FFMPEG_VARIABLES", {})
                .get(key, {})
                .get(index, {})
                .get(value, "")
            )
            msg = f"✏️ Edit/Fill this FFmpeg Variable: <u>{key}</u>\n\n<b>Item:</b> {ffc[key][int(index)]}\n\n<b>Variable:</b> {value}"
            if old_value:
                msg += f"\n\n<b>Current Value:</b> {old_value}"
            buttons.data_button("🔙 Back", f"userset {user_id} setevent")
            buttons.data_button("❌ Close", f"userset {user_id} close")
        else:
            return
        await edit_message(message, msg, buttons.build_menu(2))
        if key in ffc and value:
            pfunc = partial(set_ffmpeg_variable, key=key, value=value, index=index)
            await event_handler(client, query, pfunc)
            await ffmpeg_variables(client, query, message, user_id, key)


async def event_handler(client, query, pfunc, photo=False, document=False):
    user_id = query.from_user.id
    handler_dict[user_id] = True
    start_time = time()

    async def event_filter(_, __, event):
        if photo:
            mtype = event.photo
        elif document:
            mtype = event.document
        else:
            mtype = event.text
        user = event.from_user or event.sender_chat
        return bool(
            user.id == user_id and event.chat.id == query.message.chat.id and mtype,
        )

    handler = client.add_handler(
        MessageHandler(pfunc, filters=create(event_filter)),
        group=-1,
    )

    while handler_dict[user_id]:
        await sleep(0.5)
        if time() - start_time > 60:
            handler_dict[user_id] = False
    client.remove_handler(*handler)


@new_task
async def edit_user_settings(client, query):
    from_user = query.from_user
    user_id = from_user.id
    name = from_user.mention
    message = query.message
    data = query.data.split()
    handler_dict[user_id] = False
    thumb_path = f"thumbnails/{user_id}.jpg"
    rclone_conf = f"rclone/{user_id}.conf"
    token_pickle = f"tokens/{user_id}.pickle"
    user_dict = user_data.get(user_id, {})
    if user_id != int(data[1]):
        await query.answer("❌ Not Yours!", show_alert=True)
    elif data[2] == "setevent":
        await query.answer()
    elif data[2] in ["leech", "gdrive", "rclone", "youtube", "automation", "filename", "lulustream", "uphoster", "ffset", "watermark", "auto_thumb", "auto_thumb_format_menu", "thumbnail_menu"]:
        await query.answer()
        await update_user_settings(query, data[2])
    elif data[2] == "menu":
        await query.answer()
        if data[3] == "YT_DEFAULT_FOLDER_MODE":
            await update_user_settings(query, "youtube_folder_mode_menu")
        else:
            await get_menu(data[3], message, user_id)
    elif data[2] == "set_yt_folder_mode":
        await query.answer()
        new_mode = data[3]
        update_user_ldata(user_id, "YT_DEFAULT_FOLDER_MODE", new_mode)
        await database.update_user_data(user_id)
        await update_user_settings(query, "youtube")
    elif data[2] == "set_thumb_format":
        await query.answer()
        new_format = data[3]
        update_user_ldata(user_id, "AUTO_THUMBNAIL_FORMAT", new_format)
        await database.update_user_data(user_id)
        await update_user_settings(query, "auto_thumb")
    elif data[2] == "tog":
        await query.answer()
        update_user_ldata(user_id, data[3], data[4] == "t")

        # Determine which settings page to return to
        if data[3] == "STOP_DUPLICATE":
            back_to = "gdrive"
        elif data[3] == "USER_TOKENS":
            back_to = "main"
        elif data[3] in automation_options:
            back_to = "automation"
        elif data[3] in filename_options:
            back_to = "filename"
        elif data[3] in ["TMDB_ENABLED", "IMDB_ENABLED"]:
            back_to = "auto_thumb"
        elif data[3] in [
            "BOT_PM",
            "AS_DOCUMENT",
            "MEDIA_GROUP",
        ]:
            back_to = "leech"
        elif data[3] == "CLEAN_FILENAME":
            back_to = "filename"
        elif data[3] == "AUTO_THUMBNAIL_ENABLED":
            back_to = "thumbnail_menu"
        else:
            back_to = "leech"

        await update_user_settings(query, stype=back_to)
        await database.update_user_data(user_id)
    elif data[2] == "file":
        await query.answer()
        buttons = ButtonMaker()
        if data[3] == "THUMBNAIL":
            text = (
                "📤 Send a photo to save it as custom thumbnail. ⏱️ Timeout: 60 sec"
            )
        elif data[3] == "RCLONE_CONFIG":
            text = "📤 Send rclone.conf. ⏱️ Timeout: 60 sec"
        elif data[3] == "WATERMARK_IMAGE":
            text = "📤 Send watermark image (PNG). ⏱️ Timeout: 60 sec"
        else:
            text = "📤 Send token.pickle. ⏱️ Timeout: 60 sec"
        buttons.data_button("🔙 Back", f"userset {user_id} setevent")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        await edit_message(message, text, buttons.build_menu(1))
        pfunc = partial(add_file, ftype=data[3])
        await event_handler(
            client,
            query,
            pfunc,
            photo=data[3] == "THUMBNAIL",
            document=data[3] != "THUMBNAIL",
        )
        await get_menu(data[3], message, user_id)
    elif data[2] == "ffvar":
        await query.answer()
        key = data[3] if len(data) > 3 else None
        value = data[4] if len(data) > 4 else None
        if value == "ffmpegvarreset":
            user_dict = user_data.get(user_id, {})
            ff_data = user_dict.get("FFMPEG_VARIABLES", {})
            if key in ff_data:
                del ff_data[key]
                await database.update_user_data(user_id)
            return
        index = data[5] if len(data) > 5 else None
        await ffmpeg_variables(client, query, message, user_id, key, value, index)
    elif data[2] in ["set", "addone", "rmone"]:
        await query.answer()
        buttons = ButtonMaker()
        if data[2] == "set":
            text = user_settings_text[data[3]]
        elif data[2] == "addone":
            text = f"➕ Add one or more string key and value to {data[3]}.\n\n<b>Example:</b> {{'key 1': 62625261, 'key 2': 'value 2'}}\n\n⏱️ Timeout: 60 sec"
            func = add_one
        elif data[2] == "rmone":
            text = f"➖ Remove one or more key from {data[3]}.\n\n<b>Example:</b> key 1/key2/key 3\n\n⏱️ Timeout: 60 sec"
            func = remove_one
        buttons.data_button("🔙 Back", f"userset {user_id} setevent")
        buttons.data_button("❌ Close", f"userset {user_id} close")
        await edit_message(message, text, buttons.build_menu(1))
        if data[2] == "set":
            pfunc = partial(set_option, option=data[3])
        else:
            pfunc = partial(func, option=data[3])
        await event_handler(client, query, pfunc)
        await get_menu(data[3], message, user_id)
    elif data[2] == "remove":
        await query.answer("🗑️ Removed!", show_alert=True)
        if data[3] in ["THUMBNAIL", "RCLONE_CONFIG", "TOKEN_PICKLE", "WATERMARK_IMAGE"]:
            if data[3] == "THUMBNAIL":
                fpath = thumb_path
            elif data[3] == "RCLONE_CONFIG":
                fpath = rclone_conf
            elif data[3] == "WATERMARK_IMAGE":
                fpath = f"watermarks/{user_id}.png"
            else:
                fpath = token_pickle
            if await aiopath.exists(fpath):
                await remove(fpath)
            user_dict.pop(data[3], None)
            await database.update_user_doc(user_id, data[3])
        else:
            update_user_ldata(user_id, data[3], "")
            await database.update_user_data(user_id)
    elif data[2] == "reset":
        await query.answer("🔄 Reseted!", show_alert=True)
        if data[3] in user_dict:
            user_dict.pop(data[3], None)
        else:
            for k in list(user_dict.keys()):
                if k not in [
                    "SUDO",
                    "AUTH",
                    "THUMBNAIL",
                    "RCLONE_CONFIG",
                    "TOKEN_PICKLE",
                ]:
                    del user_dict[k]
            await update_user_settings(query)
        await database.update_user_data(user_id)
    elif data[2] == "view":
        await query.answer()
        if data[3] == "THUMBNAIL":
            await send_file(message, thumb_path, name)
        elif data[3] == "FFMPEG_CMDS":
            ffc = None
            if user_dict.get("FFMPEG_CMDS", False):
                ffc = user_dict["FFMPEG_CMDS"]
            elif "FFMPEG_CMDS" not in user_dict and Config.FFMPEG_CMDS:
                ffc = Config.FFMPEG_CMDS
            msg_ecd = str(ffc).encode()
            with BytesIO(msg_ecd) as ofile:
                ofile.name = "users_settings.txt"
                await send_file(message, ofile)
    elif data[2] == "set_upload":
        await query.answer()
        update_user_ldata(user_id, "DEFAULT_UPLOAD", data[3])
        await update_user_settings(query)
        await database.update_user_data(user_id)
    elif data[2] in [
        "gd",
        "rc",
    ]:
        await query.answer()
        du = "rc" if data[2] == "gd" else "gd"
        update_user_ldata(user_id, "DEFAULT_UPLOAD", du)
        await update_user_settings(query)
        await database.update_user_data(user_id)
    elif data[2] == "upload_dest":
        await query.answer()
        await update_user_settings(query, "upload_dest")
    elif data[2] == "back":
        await query.answer()
        await update_user_settings(query)
    else:
        await query.answer()
        await delete_message(message.reply_to_message)
        await delete_message(message)


@new_task
async def get_users_settings(_, message):
    msg = ""
    if auth_chats:
        msg += f"✅ AUTHORIZED_CHATS: {auth_chats}\n"
    if sudo_users:
        msg += f"👑 SUDO_USERS: {sudo_users}\n\n"
    if user_data:
        for u, d in user_data.items():
            kmsg = f"\n<b>👤 {u}:</b>\n"
            if vmsg := "".join(
                f"  • {k}: <code>{v or None}</code>\n" for k, v in d.items()
            ):
                msg += kmsg + vmsg
        if not msg:
            await send_message(message, "❌ No users data!")
            return
        msg_ecd = msg.encode()
        if len(msg_ecd) > 4000:
            with BytesIO(msg_ecd) as ofile:
                ofile.name = "users_settings.txt"
                await send_file(message, ofile)
        else:
            await send_message(message, msg)
    else:
        await send_message(message, "❌ No users data!")


@new_task
async def set_command(client, message):
    reply = message.reply_to_message
    if not reply:
        await send_message(message, "reply to settings or photo")
        return
    text = message.text.split()
    if len(text) == 2 and text[1] in ["-thum", "-thumbnail"]:
        if not reply.photo:
            await send_message(message, "reply to photo to set as thumbnail")
            return
        user_id = message.from_user.id
        des_dir = await create_thumb(reply, user_id)
        update_user_ldata(user_id, "THUMBNAIL", des_dir)
        await database.update_user_doc(user_id, "THUMBNAIL", des_dir)
        await send_message(message, "Thumbnail saved successfully!")
    else:
        await send_message(message, "Invalid argument. Use /set -thum by replying to photo")

def get_ddl_setting(user_id, key, default):
    user_dict = user_data.get(user_id, {})
    return user_dict.get(key, default), user_dict.get(key)
