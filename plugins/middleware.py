from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatJoinRequest

from utils import get_available_languages, get_message, storage, database

@Client.on_message(filters.private & ~filters.bot, group=-5)
async def middleware(client: Client, message: Message):
    if message.from_user: 
        user_id = message.from_user.id
        default_lang = message.from_user.language_code
        datauser = await storage.get_user(user_id)
        if datauser:
            active_user = datauser.get("active", 0)
            if not active_user:
                await database.update_user(user_id, {"active": True})
                await storage.set_user(user_id, {"active": 1})
        args = message.text.split() if message.text else []
        if not datauser or datauser.get("phase"):
            if not datauser:
                if len(args) > 1:
                    datauser = {'phase': 'lang', 'refId': args[1]}
                else:
                    datauser = {'phase': 'lang'}
                await storage.set_user(user_id, datauser)
            phase = datauser.get('phase')
            match phase:
                case 'lang':
                    buttons = []
                    languages = get_available_languages()
                    for lang in languages:
                        if lang['code'] == default_lang:
                            buttons.insert(0, [InlineKeyboardButton(lang['name'], callback_data=f"lang_{lang['code']}")])
                        else:
                            buttons.append([InlineKeyboardButton(lang['name'], callback_data=f"lang_{lang['code']}")])

                    await message.reply(
                        get_message(
                            default_lang if default_lang else "en", 
                            "signup.welcome"
                        ),
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )

                case 'sex':
                    languser = datauser.get('language', 'en')
                    await message.reply(
                        get_message(languser, "signup.sex"),
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [InlineKeyboardButton(get_message(languser, 'signup.sexbtn.male'), callback_data="sex_M"), InlineKeyboardButton(get_message(languser, 'signup.sexbtn.female'), callback_data="sex_F")]
                            ]
                        ),
                    )

            message.stop_propagation()
        else:
            if datauser.get('ban', {}).get('active'):
                unbanbtn = None
                if datauser.get('ban', {}).get('totals', 0) < 5:
                    unbanbtn = InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton(get_message(datauser['lang'], 'unban_btn'), callback_data="buy_unban")]
                        ]
                    )
                await message.reply(get_message(datauser['lang'], 'ban_alert'), reply_markup=unbanbtn)
                message.stop_propagation()
                
@Client.on_chat_join_request(group=-5)
async def check_subscription(client: Client, joinchat: ChatJoinRequest):
    user_id = joinchat.from_user.id
    user = await storage.get_user(user_id)
    if user and user.get('subscription', {}).get('active'):
        if user['subscription']['plan'] == 'vip':
            await joinchat.approve()
        else:
            await joinchat.decline()
    else:
        await joinchat.decline()
    joinchat.stop_propagation()