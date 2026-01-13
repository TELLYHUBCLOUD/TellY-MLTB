import contextlib

from pyrogram.filters import command
from pyrogram.handlers import MessageHandler

from bot import LOGGER, bot
from bot.helper.aeon_utils.terabox_helper import get_terabox_direct_link
from bot.helper.ext_utils.bot_utils import new_task
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)
from bot.modules.mirror_leech import Mirror

LOGGER.info("terabox.py module imported!")


@new_task
async def terabox_handler(client, message):
    """Handle /terabox command - Get Terabox direct download link"""
    LOGGER.info("terabox_handler triggered!")
    user_id = message.from_user.id if message.from_user else message.chat.id
    input_text = message.text.split(maxsplit=1)

    LOGGER.info(f"Terabox command received from user {user_id}")

    # Check if link is provided
    if len(input_text) < 2:
        await send_message(
            message,
            "⚠️ <b>Usage:</b> <code>/terabox &lt;link&gt;</code>\n\n"
            "Send a Terabox link to get the direct download link.",
        )
        return

    terabox_url = input_text[1].strip()
    LOGGER.info(f"Processing Terabox URL: {terabox_url}")

    # Send processing message
    wait_msg = await send_message(message, "🔄 <b>Processing Terabox link...</b>")

    try:
        # Get direct download link from API
        result = await get_terabox_direct_link(terabox_url)

        LOGGER.info(f"API Response: {result}")

        if not result.get("success"):
            error = result.get("error", "Unknown error")
            LOGGER.error(f"Terabox API failed: {error}")
            await edit_message(
                wait_msg,
                f"❌ <b>Failed to get download link</b>\n\n<b>Error:</b> {error}",
            )
            return

        # Extract file info
        direct_link = result["download_link"]
        file_name = result["file_name"]
        file_size = result["file_size"]

        LOGGER.info(f"[{user_id}] Terabox success: {file_name} ({file_size})")

        # Send file info and notify user download is starting
        await edit_message(
            wait_msg,
            f"✅ <b>File Information:</b>\n\n"
            f"<b>📁 Name:</b> <code>{file_name}</code>\n"
            f"<b>📊 Size:</b> {file_size}\n\n"
            f"⏳ <b>Starting download...</b>",
        )

        # Start mirror/leech process using auto_link to avoid link echoing
        # Pass name and size directly for accurate status message display
        await Mirror(
            client,
            message,
            is_leech=True,
            auto_link=direct_link,
            name=file_name,
            size=result.get("size_bytes", 0),
        ).new_event()

        # Delete processing message once mirror/leech has started
        await delete_message(wait_msg)

    except Exception as e:
        LOGGER.error(f"Terabox handler error: {e}", exc_info=True)
        with contextlib.suppress(BaseException):
            await edit_message(
                wait_msg,
                f"❌ <b>Error processing Terabox link</b>\n\n<code>{e!s}</code>",
            )


bot.add_handler(
    MessageHandler(
        terabox_handler, filters=command("terabox") & CustomFilters.authorized
    )
)
