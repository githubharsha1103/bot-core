import asyncio
from pyrogram import Client, filters
from pyrogram.types import BotCommandScopeChat, Message, ReplyKeyboardMarkup

from utils import get_message, storage, get_commands

@Client.on_message((filters.command("start") | filters.regex(r"^🔙")) & filters.private)
async def start(client: Client, message: Message):
    if message.from_user:
        datauser = await storage.get_user(message.from_user.id)
        if not datauser:
            return  # User not registered, let registration handler take over
        user_lang = datauser.get("lang", 'en')
        keyboard = ReplyKeyboardMarkup(get_message(user_lang, "startbtn"), resize_keyboard=True)

        commands = get_commands(user_lang)
        tasks = [
            message.reply(
                get_message(user_lang, "welcome"),
                reply_markup=keyboard
            )
        ]

        if not message.text.startswith("🔙"):
            tasks.append(client.set_bot_commands(commands, BotCommandScopeChat(message.chat.id)))

        await asyncio.gather(*tasks)
    message.stop_propagation()

@Client.on_message(filters.command("myid") & filters.private)
async def myid(client: Client, message: Message):
    await message.reply(f'🆔 User ID: `{message.from_user.id}`')
    message.stop_propagation()