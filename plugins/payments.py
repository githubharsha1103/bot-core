from pyrogram import Client, filters
from pyrogram.types import Message, PreCheckoutQuery
from pyrogram.enums import ChatMemberStatus
from pyrogram.enums import MessageServiceType
import aiohttp

from utils import storage, database, get_message, SUBSCRIPTIONS, GROUP_ID, FB_ACCESS, PIXEL_ID
from datetime import datetime, UTC, timedelta
import asyncio, logging
import time


@Client.on_pre_checkout_query(group=-9)
async def pre_checkout_query(client: Client, query: PreCheckoutQuery):
    payload = query.invoice_payload.split('-')
    match payload[0]:
        case 'premium' | 'vip':
            if not SUBSCRIPTIONS.get("star_payment", True):
                await query.answer(False, "Star payments are currently disabled")
            else:
                await query.answer(ok=True)
        case 'unban':
            user = await storage.get_user(query.from_user.id)
            if user:
                if user['ban']['totals'] >= 5:
                    await query.answer(False, "You have been banned too many times")
                elif not user['ban']['active']:
                    await query.answer(False, "You are not banned")
                else:
                    await query.answer(True)

@Client.on_message(filters.successful_payment, group=-9)
async def successful_payment(client: Client, message: Message):
    # Get payment info
    payment_info = message.successful_payment
    payload = payment_info.invoice_payload # "premium-{package_id}" or "vip-{package_id}"

    user_id = message.from_user.id
    user = await storage.get_user(user_id)

    plan_type = payload.split('-')[0]
    match plan_type:
        case 'premium' | 'vip':
            # Parse payload
            try:
                package_id = int(payload.split("-")[1])
            except:
                return # invalid payload
                
            # Get user
            lang = user.get("lang", "en")
            
            # Find package
            package = next((p for p in SUBSCRIPTIONS[plan_type]["packages"] if p["id"] == package_id), None)
            if not package:
                return await message.reply("Package not found")
            
            if plan_type == "vip":
                await client.unban_chat_member(GROUP_ID, user_id)
            
            # Calculate expiry
            duration = package["duration"]
            expires_at = datetime.now(UTC) + timedelta(days=duration)
            
            # Subscription data
            subscription_data = {
                "active": True,
                "expires_at": expires_at,
                "plan": plan_type
            }
            if user.get('refId', 'tg') not in ['tg', 'fb'] and not user.get('refId', 'tg').startswith('_tgr'):
                get_data_info = await database.get_ads_info(user['refId'])
                if get_data_info:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(f"https://graph.facebook.com/v24.0/{PIXEL_ID}/events", params={"access_token": FB_ACCESS}, json={
                            "data": [
                                {
                                    "event_name": "Purchase",
                                    "event_time": int(time.time()),
                                    "action_source": "website",
                                    "user_data": {
                                        'client_user_agent': get_data_info.get('user_agent'),
                                        'fbc': get_data_info.get('user')
                                    },
                                    "custom_data": {
                                        "currency": "USD",
                                        "value": str(payment_info.amount*0.013)
                                    }
                                }
                            ]
                        }) as resp:
                            if resp.status != 200:
                                resp_text = await resp.text()
                                logging.error(f"Error sending event to Facebook: {resp_text}")

            # Update DB
            await database.update_user(message.from_user.id, {"subscription": subscription_data})
            
            # Update Cache
            subscription_data["expires_at"] = expires_at.isoformat()
            user["subscription"] = subscription_data
            await storage.set_user(message.from_user.id, user)
            
            # Add to expiration queue
            await storage.add_subscription(message.from_user.id, expires_at.timestamp())
            
            # Reply to user
            await message.reply(get_message(lang, "subscription.success").format(expiry=expires_at.strftime("%Y-%m-%d")))
        
        case 'unban':
            lang_user = user.get("lang")
            await storage.unban_user(user_id)
            await message.reply(get_message(lang_user, 'unban_alert'))

    
    message.stop_propagation()

@Client.on_message(filters.service, group=-9)
async def check_service(client: Client, message: Message):
    type_service = message.service
    if type_service == MessageServiceType.REFUNDED_PAYMENT:
        payload = message.refunded_payment.invoice_payload
        args = payload.split("-")
        user_id = message.chat.id
        match args[0]:
            case "premium" | "vip":
                try:
                    await asyncio.gather(
                        storage.remove_subscription(user_id),
                        database.update_user(user_id, {"subscription.active": False})
                    )
                    user_data = await storage.get_user(user_id)
                    
                    get_user = await client.get_chat_member(GROUP_ID, user_id)
                    if get_user and get_user.status == ChatMemberStatus.MEMBER:
                        await client.ban_chat_member(GROUP_ID, user_id)

                    # Update Cache
                    if user_data:
                        if 'subscription' in user_data:
                            user_data['subscription']['active'] = False
                            await storage.set_user(user_id, user_data)
                except Exception as e:
                    logging.error(f"Error refunding user {user_id}: {e}")
            case "unban":
                try:
                    userdata = await storage.get_user(user_id)
                    await storage.ban_user(user_id, userdata)
                except Exception as e:
                    logging.error(f"Error refunding user {user_id}: {e}")
                    
        message.stop_propagation()
                
       