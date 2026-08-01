from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove, ReplyKeyboardMarkup, CallbackQuery, InputMediaPhoto
from pyrogram.errors import UserIsBlocked, PeerIdInvalid, InputUserDeactivated, MessageNotModified, MessageIdInvalid, QueryIdInvalid
from PIL import Image, ImageDraw, ImageFont

from utils import get_message, storage, custom_filters, database, ChatQueue
import asyncio
import re, random, io, time

chat_queue = ChatQueue()

# Precompiled regex for link/username detection (more efficient)
# Catches: http(s)://, www., t.me/, @username, and any word.tld pattern (tld = 2-6 chars)
LINK_PATTERN = re.compile(
    r"(?:https?://|www\.|t\.me/|telegram\.me/|@\w+|[a-zA-Z0-9][a-zA-Z0-9-]*\.[a-zA-Z]{2,6})\S*",
    re.IGNORECASE
)
BOT_PATTERN = re.compile(r"\b\w*bot\w*\b", re.IGNORECASE)

async def try_send(client, chat_id, text, reply_markup=None):
    try:
        await client.send_message(chat_id, text, reply_markup=reply_markup)
    except (UserIsBlocked, PeerIdInvalid, InputUserDeactivated):
        pass
async def matchmaking(user_id, userdata, to_sex: str, client: Client, premium=False):
    from_sex = userdata.get("sex")
    if not from_sex:
        await storage.set_user(user_id, {"status": "standby"})
        return
    user_lang = userdata.get("lang")
    QUEUE_KEY = f"queue:{from_sex}:{to_sex}"
    
    
    result = await storage.search_partner(QUEUE_KEY, user_id, from_sex, to_sex, int(premium))
    status_user = userdata.get('subscription', {}).get('active', False)
    if result[0] == "MATCH":
        if not status_user:
            captcha_count = userdata.get('captcha', 0)
            await storage.set_user(user_id, {'captcha': int(captcha_count) + 1}, chat=True)
        partner_data = await storage.get_user(int(result[1]))
        if not partner_data.get('subscription', {}).get('active', False):
            captcha_count = partner_data.get('captcha', 0)
            await storage.set_user(int(result[1]), {'captcha': int(captcha_count) + 1}, chat=True)

        match_msg = get_message(user_lang, "chat.match_found").format(
            get_message(user_lang, "chat.label_gender") if not status_user else partner_data.get('sex')
        )
        partner_lang = partner_data.get("lang")
        match_msg_third = get_message(partner_lang, "chat.match_found").format(
            get_message(partner_lang, "chat.label_gender") if not partner_data.get('subscription', {}).get('active', False) else userdata.get('sex')
        )
        
        # Check VIP status
        is_partner_vip = partner_data.get('subscription', {}).get('plan') == 'vip' and partner_data.get('subscription', {}).get('active', False)
        is_user_vip = userdata.get('subscription', {}).get('plan') == 'vip' and userdata.get('subscription', {}).get('active', False)

        if is_partner_vip:
            match_msg = get_message(user_lang, "vip_label") + match_msg
        
        if is_user_vip:
            match_msg_third = get_message(partner_lang, "vip_label") + match_msg_third
        await asyncio.gather(
            try_send(client, user_id, match_msg, reply_markup=ReplyKeyboardRemove()),
            try_send(client, int(result[1]), match_msg_third, reply_markup=ReplyKeyboardRemove())
        )

    return
async def gen_captcha():
    # 1. Genera operazione
    a = random.randint(10, 50)
    nums = [a]
    while len(nums) < 4:
        b = random.randint(10, 50)
        if b not in nums:
            nums.append(b)
    
    random.shuffle(nums)
    text = str(a)
    
    # 2. Crea immagine (sfondo bianco)
    W, H = 200, 200
    img = Image.new('RGB', (W, H), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    
    # 3. Aggiungi rumore
    # Linee
    for _ in range(20):
        x1 = random.randint(0, W)
        y1 = random.randint(0, H)
        x2 = random.randint(0, W)
        y2 = random.randint(0, H)
        draw.line([(x1, y1), (x2, y2)], fill=(200, 200, 200), width=2)
    
    # Cerchi/Ellissi per disturbo maggiore
    for _ in range(10):
        x1 = random.randint(0, W - 40)
        y1 = random.randint(0, H - 40)
        draw.ellipse([x1, y1, x1 + random.randint(10, 50), y1 + random.randint(10, 50)], outline=(180, 180, 180), width=2)

    # Punti
    for _ in range(100):
        xy = (random.randint(0, W), random.randint(0, H))
        draw.point(xy, fill=(150, 150, 150))

    try:
        # Tenta di caricare un font di sistema affidabile
        font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", 100)
    except IOError:
        try:
            # Fallback generico
            font = ImageFont.truetype("arial.ttf", 100)
        except IOError:
            # Fallback estremo: load_default potrebbe non supportare size su vecchie versioni di PIL
            # Ma proviamo a passare size se supportato, altrimenti default piccolo
            try:
                font = ImageFont.load_default(size=100)
            except TypeError:
                font = ImageFont.load_default()
    
    # 4. Scrivi il testo (nero) centrato
    # anchor="mm" centra il testo verticalmente e orizzontalmente rispetto alle coordinate fornite
    draw.text((W/2, H/2), text, fill=(0, 0, 0), font=font, anchor="mm")
    
    # Salva in buffer
    bio = io.BytesIO()
    img.save(bio, 'JPEG')
    bio.seek(0)

    
    btns = [[]]
    c = 0
    for num in nums:
        if c % 2 == 0 and c > 0:
            btns.append([])
        
        btns[c // 2].append(InlineKeyboardButton(str(num), callback_data=f"captcha:{num}"))
        c += 1

    markup = InlineKeyboardMarkup(btns)
    return bio, a, markup

@Client.on_message((filters.regex("^🎲") | filters.command("match")) & filters.text & filters.private & ~custom_filters.status("chatting"))
async def basic_chat(client: Client, message: Message):
    user_id = message.from_user.id
    user = await storage.get_user(user_id)
    if not user:
        return
    user_lang = user.get("lang")
    check_sub = user.get("subscription", {}).get("active", False)
    get_captcha = user.get("captcha")
    if get_captcha and not check_sub:
        if int(get_captcha) >= 30:
            captcha, captcha_text, markup = await gen_captcha()
            await storage.set_user(user_id, {"captcha_sol": captcha_text})
            await message.reply_photo(captcha, caption=get_message(user_lang, "captcha.go"), reply_markup=markup)
            message.stop_propagation()

    await try_send(client, user_id, get_message(user_lang, "chat.waiting_match"))
    await asyncio.gather(
        storage.set_user(user_id, {"status": "chatting"}, chat=True),
        matchmaking(user_id, user, 'A', client)
    )
    message.stop_propagation()

@Client.on_message(filters.regex("^[👩👨]") & filters.text & filters.private & ~custom_filters.status("chatting") & custom_filters.is_premium(True))
async def premium_chat(client: Client, message: Message):
    user_id = message.from_user.id
    user = await storage.get_user(user_id)
    if not user:
        return
    user_lang = user.get("lang")

    await message.reply(get_message(user_lang, "chat.waiting_match"))
    to_sex = "F" if message.text.startswith("👩") else "M"
    await asyncio.gather(
        storage.set_user(user_id, {"status": "chatting"}, chat=True),
        matchmaking(user_id, user, to_sex, client, True)
    )

@Client.on_callback_query(filters.regex(r"^captcha:(\d+)"))
async def check_captcha(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    clicked = int(callback_query.matches[0].group(1))
    msg = callback_query.message
    if msg is None or msg.chat is None:
        try:
            await callback_query.answer()
        except QueryIdInvalid:
            pass
        return
    
    user = await storage.get_user(user_id)
    if not user:
        return
        
    correct_sol = user.get("captcha_sol")
    
    if not correct_sol:
        # Expired or error, regenerate
        try:
            await callback_query.answer()
        except QueryIdInvalid:
            pass
        bio, sol, markup = await gen_captcha()
        await storage.set_user(user_id, {"captcha_sol": str(sol)})
        try:
            await callback_query.message.edit_media(
                media=InputMediaPhoto(bio, caption=get_message(user.get("lang"), "captcha.expired")),
                reply_markup=markup
            )
        except (MessageNotModified, MessageIdInvalid):
            pass
        return

    if clicked == int(correct_sol):
        try:
            await callback_query.answer()
        except QueryIdInvalid:
            pass
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        user_lang = user.get("lang")
        await try_send(client, user_id, get_message(user_lang, "chat.waiting_match"))
        user['captcha'] = 0
        await asyncio.gather(
            storage.set_user(user_id, {"status": "chatting", "captcha_sol": 0, "captcha": 0}),
            matchmaking(user_id, user, 'A', client)
        )
    else:
        try:
            await callback_query.answer(get_message(user.get("lang"), "captcha.failed"), show_alert=True)
        except QueryIdInvalid:
            pass
        # Regenerate
        bio, sol, markup = await gen_captcha()
        await storage.set_user(user_id, {"captcha_sol": str(sol)})
        try:
            await callback_query.message.edit_media(
                media=InputMediaPhoto(bio, caption=get_message(user.get("lang"), "captcha.go")),
                reply_markup=markup
            )
        except (MessageNotModified, MessageIdInvalid):
            pass
  
    if msg:
        msg.stop_propagation()

@Client.on_message(filters.command("stop") & filters.private & custom_filters.status("chatting") & ~custom_filters.in_chat())
async def stop_search(client: Client, message: Message):
    user_id = message.from_user.id
    user = await storage.get_user(user_id)
    if not user:
        return
    
    await asyncio.gather(
        storage.leave_queue(user_id, user.get("sex")),
        storage.set_user(user_id, {"status": "standby"}),
        try_send(client, user_id, get_message(user.get("lang"), "chat.stopped.search"), reply_markup=ReplyKeyboardMarkup(get_message(user.get("lang"), "startbtn"), resize_keyboard=True))
    )
    message.stop_propagation()

# CHAT WORKER
@Client.on_message(~filters.bot & custom_filters.in_chat() & filters.private, group=-4)
async def chatmessage(client: Client, message: Message):
    user_id = message.from_user.id
    user = await storage.get_user(user_id)
    if not user:
        return

    in_chat_value = user.get("in_chat")
    if not in_chat_value:
        return
    user_chat = int(in_chat_value)
    user_chat_data = await storage.get_user(user_chat)
    
    if not user_chat_data:
        await storage.set_user(user_id, {"status": "standby", "in_chat": 0, "last_partner": 0})
        await message.reply(get_message(user.get("lang"), "chat.stopped.partner"))
        return

    #await storage.refresh_chat_session(user_id, user_chat)
    
    if message.text:
        match message.text.lower():
            case "/stop":
                user_chat_lang = user_chat_data.get("lang")
                await asyncio.gather(
                    storage.set_user(user_id, {"status": "standby", "in_chat": 0, "last_partner": user_chat}),
                    storage.set_user(user_chat, {"status": "standby", "in_chat": 0, "last_partner": user_id}),
                    try_send(client, user_id, get_message(user.get("lang"), "chat.stopped.you"), reply_markup=ReplyKeyboardMarkup(get_message(user.get("lang"), "startbtn"), resize_keyboard=True)),
                    try_send(client, user_chat, get_message(user_chat_lang, "chat.stopped.partner"), reply_markup=ReplyKeyboardMarkup(get_message(user_chat_lang, "startbtn"), resize_keyboard=True))
                )
                message.stop_propagation()
            case '/link':
                user_chat_lang = user_chat_data.get("lang")
                button_share = InlineKeyboardMarkup([[InlineKeyboardButton(get_message(user_chat_lang, "chat.btnshareprofile"), url=f"https://t.me/{message.from_user.username}")]])

                last_send = user.get("last_send")
                if last_send and int(time.time()) - int(last_send) < 60:
                    await try_send(client, user_id, get_message(user.get("lang"), "chat.delaylink"))
                    message.stop_propagation()

                if message.from_user.username:
                    await message.reply(get_message(user.get("lang"), "chat.linksent"))
                    await try_send(client, user_chat, get_message(user_chat_lang, "chat.partnertext"), reply_markup=button_share)
                    await storage.set_user(user_id, {"last_send": int(time.time())})
                else:
                    await message.reply(get_message(user.get("lang"), "chat.nolinksent"))
                message.stop_propagation()
                

    # Check for links, usernames, or "bot" words
    text_to_check = message.text or message.caption or ""
    if LINK_PATTERN.search(text_to_check):
        await message.reply(get_message(user.get("lang"), "chat.no_links"))
        message.stop_propagation()
    elif BOT_PATTERN.search(text_to_check) and len(text_to_check) >= 5:
        message.stop_propagation()

    await chat_queue.add_message(user_chat, {
        'message': message, 
        'allowforward': not bool(user.get('allowforward')),
        'hidecontent': bool(user_chat_data.get('hidecontent'))
    })
    message.stop_propagation()

@Client.on_message(filters.command("report") & filters.private)
async def report_user_command(client: Client, message: Message):
    user_id = message.from_user.id
    user = await storage.get_user(user_id)
    lang = user.get("lang")

    target_id = int(user.get("last_partner", 0))

    if target_id == 0:
        await message.reply(get_message(lang, "report.no_user"))
        return

    reasons = get_message(lang, "report.reason")
    keyboard = []
    
    # Organize reasons in rows (e.g., 2 per row or 1 per row)
    # reasons is a dict: key -> label
    for key, label in reasons.items():
        keyboard.append([InlineKeyboardButton(label, callback_data=f"send_report_{target_id}_{key}")])
    
    await message.reply(
        get_message(lang, "report.text"),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@Client.on_callback_query(filters.regex(r"^send_report_(\d+)_(.+)"))
async def confirm_report(client: Client, callback_query: CallbackQuery):
    await callback_query.answer()
    target_id = int(callback_query.matches[0].group(1))
    reason_key = callback_query.matches[0].group(2)
    user_id = callback_query.from_user.id
    user = await storage.get_user(user_id)
    lang = user.get("lang")

    await asyncio.gather(
        database.report_user(user_id, target_id, reason_key),
        storage.set_user(user_id, {"last_partner": 0})
    )

    if callback_query.message and callback_query.message.chat:
        try:
            await callback_query.message.edit_text(
                get_message(lang, "report.success")
            )
        except MessageNotModified:
            pass