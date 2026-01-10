from bot.core.config_manager import Config
from bot.helper.ext_utils.db_handler import database
from bot.helper.telegram_helper.message_utils import send_message


async def token_check(user, message):
    if user.id != Config.OWNER_ID and (
        user.id not in Config.SUDO_USERS
        and (Config.PAID_CHANNEL_ID and Config.PAID_CHANNEL_LINK)
        and (Config.TOKEN_TIMEOUT)
    ):
        user_db = await database.db.users.find_one({"_id": user.id})
        if user_db and "expiry_time" in user_db:
            expiry_time = user_db["expiry_time"]
            current_time = time()
            if current_time < expiry_time:
                return True
        await send_message(
            message,
            f"<b>You need to join our Paid Channel to use this bot!</b>\n\n<b>Paid Channel Link:</b> {Config.PAID_CHANNEL_LINK}",
        )
        return False
    return True


async def error_check(message):
    return True
