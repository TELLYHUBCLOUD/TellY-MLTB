from asyncio import Event, wait_for
from functools import partial
from time import time

from pyrogram.filters import regex, user
from pyrogram.handlers import CallbackQueryHandler

from bot.helper.ext_utils.status_utils import get_readable_time
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)

# Store interactive session results globally to bridge between modules
# key: user_id, value: bool (Proceed or Cancel)
direct_task_results = {}


class MediaToolsSelection:
    def __init__(self, client, message, listener):
        self.client = client
        self.message = message
        self.listener = listener
        self.user_id = listener.user_id
        self.event = Event()
        self.is_cancelled = False
        self._reply_to = None
        self._timeout = 60
        self._start_time = time()

        # Flags (Synced with listener)
        self.sample_video = listener.sample_video
        self.screen_shots = listener.screen_shots
        self.convert_audio = listener.convert_audio
        self.convert_video = listener.convert_video
        self.watermark = bool(listener.watermark)
        self.metadata = bool(listener.metadata)

    async def main_menu(self):
        buttons = ButtonMaker()

        # Audio/Video Conversion Toggles
        buttons.data_button(
            f"{'✅' if self.sample_video else '❌'} Sample Video",
            "medtool toggle_sample",
        )
        buttons.data_button(
            f"{'✅' if self.screen_shots else '❌'} Screenshots", "medtool toggle_ss"
        )
        buttons.data_button(
            f"{'✅' if self.convert_audio else '❌'} Convert Audio",
            "medtool toggle_audio",
        )
        buttons.data_button(
            f"{'✅' if self.convert_video else '❌'} Convert Video",
            "medtool toggle_video",
        )

        # Watermark/Metadata (inherited from global/user settings but toggleable for specific task)
        buttons.data_button(
            f"{'✅' if self.watermark else '❌'} Watermark", "medtool toggle_wm"
        )
        buttons.data_button(
            f"{'✅' if self.metadata else '❌'} Metadata", "medtool toggle_md"
        )

        buttons.data_button("Done", "medtool done")
        buttons.data_button("Cancel", "medtool cancel")

        msg_text = (
            f"<b>Advanced Media Tools</b>\n"
            f"Select tools to apply to this task.\n\n"
            f"Timeout: {get_readable_time(max(0, self._timeout - (time() - self._start_time)))}\n"
        )

        markup = buttons.build_menu(2)

        if not self._reply_to:
            self._reply_to = await send_message(self.message, msg_text, markup)
        else:
            await edit_message(self._reply_to, msg_text, markup)

    async def get_selection(self):
        await self.main_menu()

        pfunc = partial(media_tools_callback, obj=self)
        handler = self.client.add_handler(
            CallbackQueryHandler(
                pfunc, filters=regex("^medtool") & user(self.user_id)
            ),
            group=-1,
        )

        try:
            await wait_for(self.event.wait(), timeout=self._timeout)
        except Exception:
            # Timeout
            pass
        finally:
            self.client.remove_handler(*handler)
            if self._reply_to:
                await delete_message(self._reply_to)

        if self.is_cancelled:
            return False

        # Apply flags back to listener
        self.listener.sample_video = self.sample_video
        self.listener.screen_shots = self.screen_shots
        self.listener.convert_audio = self.convert_audio
        self.listener.convert_video = self.convert_video
        # If toggled off in menu but present in listener, we keep it off.
        # If toggled on, it uses default keys from listener logic if not already set.
        if not self.watermark:
            self.listener.watermark = ""
        if not self.metadata:
            self.listener.metadata = ""

        return True


async def media_tools_callback(_, query, obj):
    data = query.data.split()
    await query.answer()

    if data[1] == "toggle_sample":
        obj.sample_video = not obj.sample_video
        await obj.main_menu()
    elif data[1] == "toggle_ss":
        obj.screen_shots = not obj.screen_shots
        await obj.main_menu()
    elif data[1] == "toggle_audio":
        obj.convert_audio = not obj.convert_audio
        await obj.main_menu()
    elif data[1] == "toggle_video":
        obj.convert_video = not obj.convert_video
        await obj.main_menu()
    elif data[1] == "toggle_wm":
        obj.watermark = not obj.watermark
        await obj.main_menu()
    elif data[1] == "toggle_md":
        obj.metadata = not obj.metadata
        await obj.main_menu()
    elif data[1] == "cancel":
        obj.is_cancelled = True
        obj.event.set()
    elif data[1] == "done":
        obj.event.set()


async def show_media_tools_for_task(client, message, listener):
    """
    Shows an interactive menu for selecting advanced media tools before a mirror/leech task starts.
    """
    selector = MediaToolsSelection(client, message, listener)
    return await selector.get_selection()


def register_pending_task_user(user_id):
    """
    Registers a user who has requested media tools to avoid race conditions.
    """
    # This might be used to pause other listeners or just mark the state
