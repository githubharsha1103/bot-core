import json
from pyrogram import Client, filters
from pyrogram.types import BotCommandScopeChat, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from utils import custom_filters, get_commands, get_message, storage, database, PAYLOAD_USER

from datetime import datetime
import asyncio

@Client.on_callback_query(custom_filters.in_registration() & ~filters.bot)
async def registration(client: Client, call: CallbackQuery):
    data = call.data.split("_")
    await call.answer()
    datauser = await storage.get_user(call.from_user.id)

    match data[0]:
        case 'lang':
            if isinstance(datauser, dict):
                datauser['phase'] = 'sex'
                datauser['language'] = data[1]
                await storage.set_user(call.from_user.id, datauser)
                try:
                    await call.message.edit(
                        get_message(str(data[1]), "signup.sex"),
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [InlineKeyboardButton(get_message(str(data[1]), 'signup.sexbtn.male'), callback_data="sex_M"), InlineKeyboardButton(get_message(str(data[1]), 'signup.sexbtn.female'), callback_data="sex_F")]
                            ]
                        ),
                    )
                except Exception:
                    pass
        
        case 'sex':
            if isinstance(datauser, dict):
                user_lang = datauser.get('language', 'en')
                kb = ReplyKeyboardMarkup(get_message(str(user_lang), "startbtn"), resize_keyboard=True)

                if call.message and call.message.chat:
                    await call.message.delete()
                commands = get_commands(user_lang)
                await asyncio.gather(
                    client.set_bot_commands(commands, BotCommandScopeChat(call.from_user.id)),
                    client.send_message(call.from_user.id, get_message(str(user_lang), "signup.signup_done"), reply_markup=kb)
                )
                new_user = {
                    'lang': datauser.get('language', 'en'),
                    'from_state': call.from_user.language_code,
                    'sex': str(data[1]),
                    'adult': False,
                    'joined_at': datetime.now(),
                    'allowforward': True,
                    'hidecontent': False,
                    'subscription': {'active': False, 'plan': 'free', 'expires_at': None},
                    'ban': {'active': False, 'totals': 0},
                    'refId': datauser.get('refId', 'tg'),
                    'active': True
                }
                payload_user = PAYLOAD_USER.copy()
                payload_user['lang'] = datauser['language']
                payload_user['sex'] = str(data[1])
                payload_user['adult'] = 0
                payload_user['allowforward'] = 1
                payload_user['hidecontent'] = 0
                payload_user['ban'] = json.dumps({'active': False, 'totals': 0})
                payload_user['subscription'] = json.dumps({'active': False, 'plan': 'free', 'expires_at': None})
                payload_user['refId'] = datauser.get('refId', 'tg')
                payload_user['active'] = 1
                await asyncio.gather(
                    database.add_user(call.from_user.id, new_user),
                    storage.set_user(call.from_user.id, payload_user, with_delete=True)
                )
    return