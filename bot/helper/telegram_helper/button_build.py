from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class ButtonMaker:
    def __init__(self):
        self._button = []
        self._header_button = []
        self._footer_button = []

    def url_button(self, key, link, position=None):
        key = self._add_emoji(key)
        if not position:
            self._button.append(InlineKeyboardButton(text=key, url=link))
        elif position == "header":
            self._header_button.append(InlineKeyboardButton(text=key, url=link))
        elif position == "footer":
            self._footer_button.append(InlineKeyboardButton(text=key, url=link))

    def data_button(self, key, data, position=None):
        key = self._add_emoji(key)
        if not position:
            self._button.append(InlineKeyboardButton(text=key, callback_data=data))
        elif position == "header":
            self._header_button.append(
                InlineKeyboardButton(text=key, callback_data=data),
            )
        elif position == "footer":
            self._footer_button.append(
                InlineKeyboardButton(text=key, callback_data=data),
            )

    def _add_emoji(self, key):
        mapping = {
            # General navigation & actions
            "Back": "⬅️",
            "Close": "🔐",
            "Next": "➡️",
            "Previous": "⬅️",
            "Done": "✅",
            "Cancel": "❌",
            "Stop": "🛑",
            "Pause": "⏸️",
            "Resume": "▶️",
            "Yes": "✅",
            "No": "❌",
            "Confirm": "✅",
            "Refresh": "🔄",
            "Retry": "🔄",
            "Home": "🏠",
            "Exit": "🚪",
            "Login": "🔑",
            "Logout": "🚪",
            "Settings": "⚙️",
            "Help": "❓",
            "Stats": "📊",
            "Status": "📈",
            "Restart": "🔄",
            "Log": "📄",
            "Shell": "🐚",
            "Search": "🔎",
            "Edit": "📝",
            "Update": "🆙",
            "Remove": "🗑️",
            "Delete": "🚮",
            "Add New": "➕",
            "Add": "➕",
            "Select": "✅",
            "Open": "📂",
            "Share": "📢",
            "Copy": "📋",
            "Paste": "📋",
            "Config": "🛠️",
            "Thumbnail": "🖼️",
            "Profile": "👤",
            "Admin": "👮",
            "User": "👤",
            "Sudo": "👮",
            "Authorize": "🔓",
            "Unauthorize": "🔒",
            # Links & Cloud
            "Cloud Link": "☁️",
            "Rclone Link": "📁",
            "Index Link": "🔗",
            "View Link": "🌐",
            "View": "🔎",
            "Link": "🔗",
            "URL": "🌐",
            "Join": "🤝",
            "Subscribe": "🔔",
            "Gdrive": "📀",
            "Rclone": "📂",
            "GoFile": "📁",
            "Pixeldrain": "💧",
            "BuzzHeavier": "🐝",
            "Terabox": "📦",
            # Media & Video Tool
            "Video Tool": "🎬",
            "Video + Audio": "🎞️",
            "Video + Subtitle": "🎞️",
            "SubSync": "⏱️",
            "Compress": "📉",
            "Convert": "🔄",
            "Watermark": "🖊️",
            "CRF": "🎞️",
            "Metadata": "🎫",
            "Extract": "📤",
            "Trim": "✂️",
            "Cut": "✂️",
            "Merge": "🔗",
            "Rename": "📝",
            "Quality": "🎞️",
            "Remove Stream": "🗑️",
            "Remove Audio": "🔇",
            "Remove Subtitle": "❌",
            "Audio": "🎵",
            "Video": "🎬",
            "Subtitle": "📝",
            "Media": "🎞️",
            "Spectrum": "📊",
            "Mediainfo": "ℹ️",
            # Task States
            "Seeding": "🌱",
            "Queued": "⏳",
            "Cloning": "👥",
            "Extracting": "📂",
            "Archiving": "📦",
            "Processing": "⚙️",
            "Checking": "🔄",
            "Success": "✅",
            "Failed": "❌",
            "Mirror": "🪞",
            "Leech": "🩸",
            "Upload": "📤",
            "Download": "📥",
            # Bots & Tools
            "Aria2": "📥",
            "Torrent": "🧲",
            "Magnet": "🧲",
            "YouTube-DLP": "🎥",
            "Playlist": "🗒️",
            "Sabnzbd": "📂",
            "Jdownloader": "📥",
            "JD Sync": "🔄",
            "NZB": "📂",
            "qBit": "📥",
            "Hydra": "🐉",
            "RSS": "📡",
            "Speedtest": "🚀",
            "Broadcast": "📢",
            "Count": "🔢",
            # Files & Misc
            "File": "📄",
            "Folder": "📁",
            "Pvt Files": "🔒",
            "Default": "🔄",
            "Empty": "🫙",
            "Servers": "🖥️",
            "Info": "ℹ️",
            "Zip": "📦",
            "Rar": "📦",
            "7z": "📦",
            "All": "🌟",
        }
        for word, emoji in mapping.items():
            if word.lower() in key.lower() and emoji not in key:
                return f"{emoji} {key}"
        return key

    def build_menu(self, b_cols=1, h_cols=8, f_cols=8):
        menu = [
            self._button[i : i + b_cols] for i in range(0, len(self._button), b_cols)
        ]
        if self._header_button:
            h_cnt = len(self._header_button)
            if h_cnt > h_cols:
                header_buttons = [
                    self._header_button[i : i + h_cols]
                    for i in range(0, len(self._header_button), h_cols)
                ]
                menu = header_buttons + menu
            else:
                menu.insert(0, self._header_button)
        if self._footer_button:
            if len(self._footer_button) > f_cols:
                [
                    menu.append(self._footer_button[i : i + f_cols])
                    for i in range(0, len(self._footer_button), f_cols)
                ]
            else:
                menu.append(self._footer_button)
        return InlineKeyboardMarkup(menu)

    def reset(self):
        self._button = []
        self._header_button = []
        self._footer_button = []
