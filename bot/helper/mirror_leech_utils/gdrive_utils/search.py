import logging

from bot.helper.ext_utils.status_utils import get_readable_file_size
from bot.helper.mirror_leech_utils.gdrive_utils.helper import GoogleDriveHelper

LOGGER = logging.getLogger(__name__)


class GoogleDriveList(GoogleDriveHelper):
    def __init__(self, listener):
        self.listener = listener
        self._is_cancelled = False
        super().__init__()

    async def get_list(self, target_id):
        if self._is_cancelled:
            return None, None
        try:
            return self.get_files_by_folder_id(target_id), None
        except Exception as e:
            return None, str(e)

    async def drive_list(self, file_name, target_id="", user_id=""):
        if not target_id:
            target_id = self.listener.user_dict.get("GDRIVE_ID") or self.G_DRIVE_ID
        if not target_id:
            return "GDRIVE_ID not Found!", None, None, None

        if (
            target_id.startswith("mtp:")
            or (not target_id.startswith("mtp:") and len(self.drives_ids) > 1)
        ) or target_id.startswith("tp:"):
            self.use_sa = False

        if target_id.startswith("mtp:"):
            target_id = target_id.replace("mtp:", "", 1)
            self.token_path = f"tokens/{user_id}.pickle"
            self.use_sa = False
        elif target_id.startswith("tp:"):
            target_id = target_id.replace("tp:", "", 1)
            self.token_path = "token.pickle"
            self.use_sa = False
        elif target_id.startswith("sa:"):
            target_id = target_id.replace("sa:", "", 1)
            self.use_sa = True

        try:
            query = f"name contains '{file_name}' and trashed = false"
            if target_id != "root":
                query += f" and '{target_id}' in parents"
            files = self.get_files_by_query(query)
        except Exception as e:
            return str(e), None, None, None

        if not files:
            return "No files found!", None, None, None

        msg = ""
        button = None

        for file in files:
            file_url = file.get("webViewLink")
            if file.get("mimeType") == self.G_DRIVE_DIR_MIME_TYPE:
                msg += f"📁 <code>{file.get('name')}</code> (Folder)\n"
                msg += f"<a href='{file_url}'>Drive Link</a>"
            else:
                msg += f"📄 <code>{file.get('name')}</code> ({get_readable_file_size(int(file.get('size', 0)))})\n"
                msg += f"<a href='{file_url}'>Drive Link</a>"

            if self.INDEX_URL:
                url = f"{self.INDEX_URL}findpath?id={file.get('id')}"
                msg += f" | <a href='{url}'>Index Link</a>"
                if file.get("mimeType").startswith(("video", "audio", "image")):
                    url_view = (
                        f"{self.INDEX_URL}findpath?id={file.get('id')}&view=true"
                    )
                    msg += f" | <a href='{url_view}'>View Link</a>"
            msg += "\n\n"

        return msg, button, None, None
