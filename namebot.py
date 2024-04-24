#! /usr/bin/python

"""
NameBot - Your Partner in Banning Assholes Who Sell Shit in Your Groups
Authored by Shinanygans (shinanygans@proton.me)

This bot will scan the display name of anyone who posts in your group, and ban them if the names contain certain listed words.
"""

import logging
from logging.handlers import TimedRotatingFileHandler
import asyncio
import re
from functools import wraps
from telegram import Update, Message
from telegram.constants import ChatType, ParseMode

from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    Application
)
from config import (
    BOT_TOKEN,
    BANNED_WORDS,
    AUTHORIZED_ADMINS

)

# Configure logging
when = 'midnight'  # Rotate logs at midnight (other options include 'H', 'D', 'W0' - 'W6', 'MIDNIGHT', or a custom time)
interval = 1  # Rotate daily
backup_count = 7  # Retain logs for 7 days
log_handler = TimedRotatingFileHandler('app.log', when=when, interval=interval, backupCount=backup_count)
log_handler.suffix = "%Y-%m-%d"  # Suffix for log files (e.g., 'my_log.log.2023-10-22')

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        log_handler,
    ]
)

# Create a separate handler for console output with a higher level (WARNING)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)  # Set the level to WARNING or higher
console_formatter = logging.Formatter("NAMEBOT: %(message)s")
console_handler.setFormatter(console_formatter)

# Attach the console handler to the root logger
logging.getLogger().addHandler(console_handler)


# Global variables
namebot = None
app = None
authorized_chats = []
regex_pattern = re.compile('|'.join(map(re.escape, BANNED_WORDS)), re.IGNORECASE)
active = True
authorized_admin_set = set(AUTHORIZED_ADMINS)


# Custom decorator function to check if the requesting user is authorized (use for commands).
def authorized_admin_check(handler_function):
    @wraps(handler_function)
    async def wrapper(update: Update, context: CallbackContext):
        try:
            user_id = update.effective_user.id
            if AUTHORIZED_ADMINS and user_id not in AUTHORIZED_ADMINS:
                return 
            else:
                return await handler_function(update, context)

        except Exception as e:
            logging.warning(f"An error occured in authorized_admin_check(): {e}")
            return
    return wrapper


def authorized_chat_check(handler_function):
    @wraps(handler_function)
    async def wrapper(update: Update, context: CallbackContext):
        try:
            chat_id=update.effective_chat.id
            if chat_id in authorized_chats:
                return await handler_function(update, context)
            
            is_auth = await is_chat_authorized(chat_id)
            if is_auth:
                return await handler_function(update, context)
            else:
                return

        except Exception as e:
            logging.warning(f"An error occured in authorized_admin_check(): {e}")
            return
    return wrapper


async def delete_message_after_delay(message:Message):
    try:
        await asyncio.sleep(3)  # Wait for 3 seconds
        await namebot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
    except Exception as e:
        logging.warning("Error deleting message.")
    return


async def is_chat_authorized(chat_id: int):
    if chat_id in authorized_chats:
        return True
    try:
        chat_admins = await namebot.get_chat_administrators(chat_id)
        admin_ids = {admin.user.id for admin in chat_admins}
        if admin_ids.intersection(authorized_admin_set):
            chat_member = await namebot.get_chat_member(chat_id, namebot.id)
            is_admin = chat_member.status in ["administrator", "creator"]
            if is_admin:
                authorized_chats.append(chat_id)
                logging.warning(f"Chat {chat_id} added to authoized chats")
                return True
        return False
    except Exception as e:
        logging.error(f"Error checking if chat {chat_id} is authorized: {e}")
        return False



async def ban_user_in_chat(chat_id: int, user_id: int):
    try:
        await namebot.ban_chat_member(chat_id, user_id)
        
    except Exception as e:
        logging.error(f"Error banning user {user_id} in chat {chat_id}: {e}")
        return False
    return True


async def send_ban_confirmation_message_to_chat(chat_id: int, user_id: int, matched_string: str):
    try:
        message = await namebot.send_message(
            chat_id, 
            f"User {user_id} has been banned for having the word {matched_string} in his name.", 
            parse_mode=ParseMode.HTML
        )
        logging.error(f"User {user_id} has been banned for having the word {matched_string} in his name.")

        asyncio.create_task(delete_message_after_delay(message))
    except Exception as e:
        logging.error(f"Error sending ban confirmation message to chat {chat_id}: {e}")
        return False
    return True


async def handle_message(update: Update, context: CallbackContext):
    try:
        if not active:
            return
        
        if update.message is None or hasattr(update.message, "chat") is False or update.message.chat is None:
            return

        chat_type = update.message.chat.type

        # Exclude private chats with the bot
        if chat_type == ChatType.PRIVATE:
            return
            
        full_name = update.message.from_user.full_name
        user_id = update.message.from_user.id
        chat_id = update.message.chat.id

        # If the user's full name contains the words in the banned words list, ban them
        match = regex_pattern.search(full_name)

        if match is not None:
            await ban_user_in_chat(chat_id, user_id)
            await send_ban_confirmation_message_to_chat(chat_id, user_id, match.group())
            
    except Exception as e:
        logging.error(f"Error handling message: {e}")
    return

# Authorization for this function is handled at the calling function level
async def toggle(update: Update, context: CallbackContext):
    global active
    try:
        is_admin = await is_chat_authorized(update.message.chat.id)
        if not is_admin:
            return

        if active:
            await update.message.reply_text("NameBot has been deactivated in this chat.")
            logging.warning("NameBot has been deactivated in this chat.")
            active=False
            return

        await update.message.reply_text("NameBot is now active in this chat.")
        logging.warning("NameBot is now active in this chat.")
        active = True
    except Exception as e:
        logging.error(f"Error starting NameBot: {e}")
    return


#############  ASYNCIO TASK FUNCTIONS  #############

@authorized_chat_check
@authorized_admin_check
async def start_loop(update: Update, context: CallbackContext):
    asyncio.create_task(toggle(update, context))
    return

@authorized_chat_check
async def handle_message_loop(update: Update, context: CallbackContext):
    asyncio.create_task(handle_message(update, context))
    return



#############  MAIN FUNCTION  #############

def main() -> None:
    global namebot
    global app

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("namebot", start_loop))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message_loop))

    try:
        namebot = application.bot
        app = application

        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        print(e)


if __name__ == "__main__":
    main()