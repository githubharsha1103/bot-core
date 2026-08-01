import asyncio
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, BotCommandScopeChat
from pyrogram.errors import MessageDeleteForbidden, MessageNotModified
from utils import custom_filters, get_message, storage, database, get_available_languages, get_commands

def template_data(lang: str, allowforward: int, hidecontent: int):
    allowforward = int(allowforward or 0)
    hidecontent = int(hidecontent or 0)

    msg_settings = get_message(lang, "settings.label").format(
            get_message(lang, f"settings.bool.forward.{allowforward}"),
            get_message(lang, f"settings.bool.hidecontent.{hidecontent}")
        )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_message(lang, f"settings.buttons.forward.{int(not allowforward)}"), callback_data="forward")],
        [InlineKeyboardButton(get_message(lang, f"settings.buttons.hidecontent.{int(not hidecontent)}"), callback_data="hidecontent")],
        [InlineKeyboardButton(get_message(lang, "settings.buttons.lang.labelbtn"), callback_data="lang")]
    ])

    return msg_settings, markup

@Client.on_message(filters.command("settings") & filters.private & ~custom_filters.status("chatting"))
async def settings(client: Client, message: Message):
    user = await storage.get_user(message.from_user.id)
    if user:
        lang = user.get("lang")
        allowforward = user.get("allowforward")
        hidecontent = user.get("hidecontent")
        
        msg_settings, markup = template_data(lang, allowforward, hidecontent)
        await message.reply(msg_settings, reply_markup=markup)

@Client.on_callback_query(filters.regex(r"^(forward|hidecontent)$") & ~custom_filters.status("chatting"))
async def settings_callback(client: Client, query: CallbackQuery):
    await query.answer()
    user = await storage.get_user(query.from_user.id)
    if not user:
        return

    key_map = {
        "forward": "allowforward",
        "hidecontent": "hidecontent"
    }
    
    user_key = key_map[query.data]
    current_val = int(user.get(user_key) or 0)
    new_val = int(not current_val)
    lang = user.get("lang") or "en"
    
    user[user_key] = new_val
    msg_settings, markup = template_data(lang, user.get("allowforward"), user.get("hidecontent"))
    
    tasks = [
        storage.set_user(query.from_user.id, user),
        database.update_user(query.from_user.id, {user_key: bool(new_val)})
    ]
    if query.message and query.message.chat:
        tasks.append(query.message.edit(msg_settings, reply_markup=markup))

    await asyncio.gather(*tasks)
    
@Client.on_callback_query(filters.regex("^lang") & ~custom_filters.status("chatting"))
async def select_language(client: Client, query: CallbackQuery):
    await query.answer()
    user = await storage.get_user(query.from_user.id)
    if not user:
        return
    
    args = query.data.split("_")
    if len(args) > 1:
        newlang = args[1]
        user["lang"] = newlang
        commands = get_commands(newlang)

        await asyncio.gather(
            storage.set_user(query.from_user.id, user),
            database.update_user(query.from_user.id, {"lang": newlang}),
            client.set_bot_commands(commands, BotCommandScopeChat(query.from_user.id))
        )

        keyboard = ReplyKeyboardMarkup(get_message(newlang, "startbtn"), resize_keyboard=True)
        try:
            if query.message and query.message.chat:
                await query.message.delete()
        except MessageDeleteForbidden:
            pass
        await client.send_message(query.from_user.id, get_message(newlang, "settings.buttons.lang.done"), reply_markup=keyboard)
        return
    
    userlang = user.get("lang") or "en"
    buttons = [[]]
    c = 0
    languages = get_available_languages()
    for lang in languages:
        if c % 2 == 0:
            buttons.append([])
        buttons[c // 2].append(InlineKeyboardButton(lang['name'], callback_data=f"lang_{lang['code']}"))
        c += 1
    
    if query.message and query.message.chat:
        try:
            await query.message.edit(get_message(userlang, "settings.buttons.lang.labeltext"), reply_markup=InlineKeyboardMarkup(buttons))
        except MessageNotModified:
            pass
    return