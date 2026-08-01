from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, Message

from pyrogram.errors import MessageNotModified
from utils import get_message, storage, custom_filters, SUBSCRIPTIONS

import json
import logging
from datetime import datetime

durations = {
    7: '1 week',
    30: '1 month',
    90: '3 months',
    180: '6 months',
    360: '1 year'
}

def get_discounted_price(price, discount_percent):
    if not discount_percent:
        return price
    return price * (1 - discount_percent / 100)
async def process_promo_code(client, message, code, user):
    lang = user.get("lang", "en")
    
    promocodes = SUBSCRIPTIONS.get("promocodes", {})
    promo_data = promocodes.get(code)
    
    if promo_data:
        if not promo_data.get("active"):
            await message.reply(get_message(lang, "promocode.invalid"))
            return
        # Apply discount
        await storage.set_user(message.chat.id, {
            "status": "standby",
            "promo_discount": promo_data['value'],
            "promo_code": code
        })
        await message.reply(get_message(lang, "promocode.valid").format(promo_data['value']))
        # Show packages
        await premium_command(client, message)
    else:
        await storage.set_user(message.chat.id, {"status": "standby"})
        await message.reply(get_message(lang, "promocode.invalid"))

def is_promo_active(code):
    try:
        promo = SUBSCRIPTIONS.get("promocodes", {}).get(code)
        if promo and isinstance(promo, dict) and promo.get("active"):
            return True, promo.get("value")
        return False, 0
    except:
        return False, 0

@Client.on_message(filters.command(["premium", "vip"]))
async def premium_command(client: Client, message: Message, back=False, vip=False):
    user = await storage.get_user(message.chat.id)
    lang = user.get("lang", "en")

    if message.command:
        if message.command[0] == "vip":
            vip = True
    
    if back:
        try:
            if not vip:
                await message.edit_text(get_message(lang, "subscription.info"), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_message(lang, "subscription.btn_buy"), callback_data="premium_buy")]]))
            else:
                await message.edit_text(get_message(lang, "subscription.info_vip"), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_message(lang, "subscription.btn_buy_vip"), callback_data="vip_buy")]]))
        except MessageNotModified:
            pass
    else:
        # Check if user has active subscription
        sub_data = user.get("subscription", {})
        if isinstance(sub_data, str):
            try:
                sub_data = json.loads(sub_data)
            except:
                sub_data = {}
        
        if sub_data.get("active"):
            expires_at = sub_data.get("expires_at")
            # Parse expiry date
            if isinstance(expires_at, str):
                try:
                    expires_dt = datetime.fromisoformat(expires_at)
                    expiry_str = expires_dt.strftime("%d/%m/%Y")
                except:
                    expiry_str = str(expires_at)
            else:
                 # Should not happen typically if loaded from redis as str, but if direct from mongo or fresh object
                 expiry_str = expires_at.strftime("%d/%m/%Y") if hasattr(expires_at, "strftime") else str(expires_at)

            await message.reply(get_message(lang, "subscription.status_active").format(expiry=expiry_str, plan=sub_data.get("plan").capitalize()))
        else:
            await message.reply(
                get_message(lang, "subscription.info" if not vip else "subscription.info_vip"),
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton(get_message(lang, "subscription.btn_buy" if not vip else "subscription.btn_buy_vip"), callback_data="premium_buy" if not vip else "vip_buy")]
                    ]
                )
            )
        
    return

@Client.on_message(filters.command("promocode"))
async def promocode_command(client: Client, message: Message):
    user = await storage.get_user(message.chat.id)
    lang = user.get("lang", "en")

    # Check for arguments
    if len(message.command) > 1:
        code = message.command[1]
        await process_promo_code(client, message, code, user)
    else:
        # Ask for code
        await storage.set_user(message.chat.id, {"status": "waiting_promo"})
        await message.reply(get_message(lang, "promocode.text_input"))

@Client.on_message(custom_filters.status("waiting_promo") & filters.text & ~filters.bot)
async def promo_input_handler(client: Client, message: Message):
    user = await storage.get_user(message.chat.id)
    await process_promo_code(client, message, message.text, user)

@Client.on_callback_query(filters.regex("^premium_buy$") & ~custom_filters.is_premium())
async def premium_buy(client: Client, call: CallbackQuery):
    user = await storage.get_user(call.from_user.id)
    lang = user.get("lang", "en")
    
    buttons = []
    for package in SUBSCRIPTIONS["premium"]["packages"]:
        price_stars = package["price"][0]
        
        # Calculate discount
        discount_percent = int(user.get("promo_discount", 0))
        promo_code = user.get("promo_code")
        
        if discount_percent > 0:
            is_active, new_percent = is_promo_active(promo_code)
            if not is_active:
                discount_percent = 0
            elif new_percent != discount_percent:
                discount_percent = new_percent

        if discount_percent > 0:
            price_stars_final = int(get_discounted_price(price_stars, discount_percent))
            display_price = f"{price_stars_final} ⭐ ({discount_percent}%)"
        else:
            display_price = f"{price_stars} ⭐"

        duration = str(package['duration'])

        buttons.append(
            [InlineKeyboardButton(
                f"{display_price} - {get_message(lang, 'subscription.days.' + duration)}",
                callback_data=f"pay_P{package['id']}"
            )]
        )
        
    buttons.append([InlineKeyboardButton(get_message(lang, "subscription.back"), callback_data="premium_back")])
    
    if call.message and call.message.chat:
        try:
            await call.message.edit(
                get_message(lang, "subscription.packages"),
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except MessageNotModified:
            await call.answer()

@Client.on_callback_query(filters.regex("^vip_buy$") & ~custom_filters.is_premium(is_vip=True))
async def vip_buy(client: Client, call: CallbackQuery):
    user = await storage.get_user(call.from_user.id)
    lang = user.get("lang", "en")
    
    buttons = []
    for package in SUBSCRIPTIONS["vip"]["packages"]:
        price_stars = package["price"][0]
        
        # Calculate discount
        discount_percent = int(user.get("promo_discount", 0))
        promo_code = user.get("promo_code")
        
        if discount_percent > 0:
            is_active, new_percent = is_promo_active(promo_code)
            if not is_active:
                discount_percent = 0
            elif new_percent != discount_percent:
                discount_percent = new_percent

        if discount_percent > 0:
            price_stars_final = int(get_discounted_price(price_stars, discount_percent))
            display_price = f"{price_stars_final} ⭐ ({discount_percent}%)"
        else:
            display_price = f"{price_stars} ⭐"

        duration = str(package['duration'])

        buttons.append(
            [InlineKeyboardButton(
                f"{display_price} - {get_message(lang, 'subscription.days.' + duration)}",
                callback_data=f"pay_V{package['id']}"
            )]
        )
        
    buttons.append([InlineKeyboardButton(get_message(lang, "subscription.back"), callback_data="vip_back")])
    
    if call.message and call.message.chat:
        try:
            await call.message.edit(
                get_message(lang, "subscription.packages"),
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except MessageNotModified:
            await call.answer()

@Client.on_callback_query(filters.regex("^pay_"))
async def pay_package(client: Client, call: CallbackQuery):
    # data format: pay_P1 or pay_V1
    data_str = call.data.split("_")[1]
    plan_type = data_str[0] # P or V
    package_id = int(data_str[1:])
    
    user = await storage.get_user(call.from_user.id)
    lang = user.get("lang", "en")
    
    # Find package
    plan_key = "premium" if plan_type == "P" else "vip"
    package = next((p for p in SUBSCRIPTIONS[plan_key]["packages"] if p["id"] == package_id), None)
    
    if not package:
        return await call.answer("Package not found", show_alert=True)

    buttons = [[InlineKeyboardButton(get_message(lang, "subscription.pay_btn"), callback_data=f"paymethod_stars_{plan_type}_{package_id}")]]

    back_cb = "premium_buy" if plan_type == "P" else "vip_buy"
    buttons.append([InlineKeyboardButton(get_message(lang, "subscription.back"), callback_data=back_cb)])

    if call.message and call.message.chat:
        try:
            await call.message.edit(
                get_message(lang, "subscription.payment_method"),
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        except MessageNotModified:
            await call.answer()

@Client.on_callback_query(filters.regex("^premium_back$") & ~custom_filters.is_premium())
async def premium_back(client: Client, call: CallbackQuery):
    if call.message and call.message.chat:
        await premium_command(client, call.message, True)

@Client.on_callback_query(filters.regex("^vip_back$") & ~custom_filters.is_premium(is_vip=True))
async def vip_back(client: Client, call: CallbackQuery):
    if call.message and call.message.chat:
        await premium_command(client, call.message, True, True)

@Client.on_callback_query(filters.regex("^paymethod_"))
async def select_payment_method(client: Client, call: CallbackQuery):
    data = call.data.split("_")
    # paymethod_stars_P_123 -> ['paymethod', 'stars', 'P', '123']
    method_type = data[1]

    if method_type != "stars":
        return await call.answer("Only Telegram Stars payments are available.", show_alert=True)

    user = await storage.get_user(call.from_user.id)
    lang = user.get("lang", "en")

    plan_type = data[2]
    package_id = int(data[3])

    plan_key = "premium" if plan_type == "P" else "vip"
    info_package = next((p for p in SUBSCRIPTIONS[plan_key]["packages"] if p["id"] == package_id), None)

    if not info_package:
        return await call.answer("Package not found", show_alert=True)

    price_stars_final = info_package["price"][0]

    discount_percent = int(user.get("promo_discount", 0))
    promo_code = user.get("promo_code")

    if discount_percent > 0:
        is_active, new_percent = is_promo_active(promo_code)
        if not is_active:
            await storage.set_user(call.from_user.id, {"promo_discount": 0, "promo_code": ""})
            await call.answer(get_message(lang, "promocode.expired_alert"), show_alert=True)
            return await premium_command(client, call.message, back=False)
        price_stars_final = int(get_discounted_price(price_stars_final, new_percent))

    plan_title = "Premium" if plan_key == "premium" else "VIP"
    get_link = await client.create_invoice_link(
        title=f"{plan_title} {durations[info_package['duration']]} | {call.from_user.id}",
        description=f"Buy {plan_key} subscription",
        payload=f"{plan_key}-{package_id}",
        provider_token='',
        start_parameter="1",
        currency="XTR",
        prices=[
            LabeledPrice(f"{plan_title} Subscription", price_stars_final)
        ],
        subscription_period = 2592000 if info_package['duration'] == 30 else None
    )

    if call.message and call.message.chat:
        await call.edit_message_text(
            get_message(lang, "subscription.pay_info"),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_message(lang, "subscription.pay_btn"), url=get_link, pay=True)]])
        )
                 
