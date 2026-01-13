from pyrogram.filters import create

from bot import auth_chats, sudo_users, user_data
from bot.core.config_manager import Config


class CustomFilters:
    async def owner_filter(self, _, update):
        user = update.from_user or update.sender_chat
        return user.id == Config.OWNER_ID

    owner = create(owner_filter)

    async def authorized_user(self, _, update):
        user = update.from_user or update.sender_chat
        uid = user.id
        msg = update if hasattr(update, "chat") else getattr(update, "message", None)
        chat_id = msg.chat.id if msg else uid
        thread_id = (
            msg.message_thread_id
            if msg and hasattr(msg, "topic_message") and msg.topic_message
            else None
        )
        return bool(
            uid == Config.OWNER_ID
            or (
                uid in user_data
                and (
                    user_data[uid].get("AUTH", False)
                    or user_data[uid].get("SUDO", False)
                )
            )
            or (
                chat_id in user_data
                and user_data[chat_id].get("AUTH", False)
                and (
                    thread_id is None
                    or thread_id in user_data[chat_id].get("thread_ids", [])
                )
            )
            or uid in sudo_users
            or uid in auth_chats
            or (
                chat_id in auth_chats
                and (
                    (
                        auth_chats[chat_id]
                        and thread_id
                        and thread_id in auth_chats[chat_id]
                    )
                    or not auth_chats[chat_id]
                )
            ),
        )

    authorized = create(authorized_user)

    async def sudo_user(self, _, update):
        user = update.from_user or update.sender_chat
        uid = user.id
        return bool(
            uid == Config.OWNER_ID
            or (uid in user_data and user_data[uid].get("SUDO"))
            or uid in sudo_users,
        )

    sudo = create(sudo_user)
