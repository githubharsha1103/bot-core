from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import QueryIdInvalid

from utils import custom_filters, get_message, storage, CREATORS, INVITE_LINK

@Client.on_message(filters.regex("^🔥") & filters.private & filters.text & custom_filters.is_adult() & custom_filters.is_premium(True, is_vip=True))
@Client.on_callback_query(filters.regex("accept"))
async def sexchat(client: Client, message: Message | CallbackQuery):
    user = await storage.get_user(message.from_user.id)
    if isinstance(message, CallbackQuery):
        await message.answer()
        await storage.update_adult(message.from_user.id)
        message = message.message
        try:
            await message.edit_text(get_message(user.get('lang'), "sexchat.accepted"))
        except Exception:
            pass
        message.stop_propagation()

    await message.reply_text(get_message(user.get('lang'), "sexchat.info"), reply_markup=ReplyKeyboardMarkup(get_message(user.get('lang'), "sexchat.menu_btn"), resize_keyboard=True))
    message.stop_propagation()

@Client.on_message(filters.regex("^👑") & filters.private & filters.text & custom_filters.is_adult() & custom_filters.is_premium(True, is_vip=True))
async def sexchat_vip_group(client: Client, message: Message):
    user = await storage.get_user(message.from_user.id)
    btn = InlineKeyboardMarkup([[InlineKeyboardButton(get_message(user.get('lang', 'en'), "sexchat.join_group"), url=INVITE_LINK)]])
    await message.reply(get_message(user.get('lang'), "sexchat.vip_group_info"), reply_markup=btn)
    message.stop_propagation()

@Client.on_message(filters.regex("^❤️‍🔥") & filters.private & filters.text & custom_filters.is_adult() & custom_filters.is_premium(True, is_vip=True))
async def sexchat_girls(client: Client, message: Message):
    user = await storage.get_user(message.from_user.id)
    
    c = 0
    buttons = [[]]
    for id_cr, data_creator in CREATORS.items():
        name = data_creator.get("name")
        username = data_creator.get("username")
        if name and username:
            if c % 3 == 0:
                buttons.append([])
            buttons[c // 3].append(InlineKeyboardButton(name, callback_data=f"creator_{id_cr}"))
            c += 1

    await message.reply(get_message(user.get('lang'), "sexchat.girls_intro"), reply_markup=InlineKeyboardMarkup(buttons))
    message.stop_propagation()

@Client.on_callback_query(filters.regex("^creator_") & custom_filters.is_premium(True, is_vip=True))
async def creator_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    id_cr = int(callback_query.data.split("_")[1])
    user = await storage.get_user(callback_query.from_user.id)
    
    selected_creator = CREATORS.get(id_cr)
    
    if selected_creator:
        name = selected_creator.get("name")
        username = selected_creator.get("username")
        caption = get_message(user.get('lang'), "sexchat.creator_profile").format(name=name)
        
        button = InlineKeyboardMarkup([[]])
        if selected_creator.get("can_chat"):
            button.inline_keyboard[0].append(InlineKeyboardButton(get_message(user.get('lang'), "sexchat.start_chat"), url=f"https://t.me/{username}"))
        if selected_creator.get("album"):
            button.inline_keyboard[0].append(InlineKeyboardButton(get_message(user.get('lang'), "sexchat.album_photo"), callback_data=f"album_{id_cr}"))
        
        await callback_query.edit_message_text(caption, reply_markup=button)

    if callback_query.message:
        callback_query.message.stop_propagation()

@Client.on_callback_query(filters.regex("^album_") & custom_filters.is_premium(True, is_vip=True))
async def album_callback(client: Client, callback_query: CallbackQuery):
    try:
        await callback_query.answer()
    except QueryIdInvalid:
        pass
    user = await storage.get_user(callback_query.from_user.id)
    id_cr = int(callback_query.data.split("_")[1])
    selected_creator = CREATORS.get(id_cr)
    if not selected_creator:
        return
    album = selected_creator.get("album_data")
    if album and callback_query.message and callback_query.message.chat:
        await client.copy_media_group(callback_query.message.chat.id, *album, captions=get_message(user.get('lang'), "sexchat.album_info"), protect_content=True)
    elif not album:
        if callback_query.message and callback_query.message.chat:
            await callback_query.edit_message_text(get_message(user.get('lang'), "sexchat.album_not_found"))
    
    if callback_query.message:
        callback_query.message.stop_propagation()
