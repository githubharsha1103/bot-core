from pyrogram import Client, filters
from pyrogram.types import Message
from utils import get_message, storage, SUPPORT

@Client.on_message(filters.command("about") & filters.private)
async def about(client: Client, message: Message):
    user = await storage.get_user(message.from_user.id)
    if not user:
        return
    
    lang = user.get("lang")
    await message.reply(get_message(lang, "about_text"))

@Client.on_message(filters.command(["paysupport", 'support']) & filters.private)
async def paysupport(client: Client, message: Message):
    user = await storage.get_user(message.from_user.id)
    if not user:
        return
    
    lang = user.get("lang")
    await message.reply(get_message(lang, "paysupport_text").format(SUPPORT))