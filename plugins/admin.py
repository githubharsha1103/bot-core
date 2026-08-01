import os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import MessageNotModified
import aiohttp

from utils import storage, ADMINS, get_available_languages, get_message, database, custom_filters, CHANNEL_ID, CREATORS, broadcast_manager, GROUP_ID, update_subscription_price
import asyncio
from datetime import datetime, timedelta, UTC
import json

processed_media_groups = {}
READFEED_PER_PAGE = 1

async def _build_feedback_page(page: int):
    """Build the text and inline keyboard for a single feedback entry."""
    items, total = await database.get_feedback_page(page, READFEED_PER_PAGE)

    if not items:
        return "📭 Nessun feedback trovato.", None

    total_pages = max(1, total)
    page = min(page, total_pages - 1)
    item = items[0]

    uid = item.get("user_id", "?")
    ts = item.get("timestamp")
    ts_str = ts.strftime("%d/%m/%Y %H:%M") if ts else "N/A"
    content = item.get("feedback_content", "")

    text = (
        f"📋 **Feedback {page + 1}/{total_pages}**\n\n"
        f"👤 **Utente:** `{uid}`\n"
        f"🕐 **Data:** {ts_str}\n\n"
        f"💬 {content}"
    )

    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton("◀️", callback_data=f"readfeed:{page - 1}"))
    buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="readfeed:noop"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton("▶️", callback_data=f"readfeed:{page + 1}"))

    return text, InlineKeyboardMarkup([buttons])

@Client.on_message(filters.command("updatecf") & filters.user(ADMINS), group=-10)
async def update_langs(client: Client, message: Message):
    get_available_languages(reset=True)
    await message.reply("Update completed!")
    message.stop_propagation()

@Client.on_message(filters.command("restart") & filters.user(ADMINS), group=-10)
async def restart(client: Client, message: Message):
    await message.reply("🔄 **Riavvio del bot in corso...**")
    import sys
    from dotenv import load_dotenv
    load_dotenv(override=True)
    os.execl(sys.executable, sys.executable, "main.py")

@Client.on_message(filters.command("setprice") & filters.user(ADMINS), group=-10)
async def setprice(client: Client, message: Message):
    args = message.text.split()
    if len(args) != 4 or args[0].lower() != "/setprice":
        await message.reply("Usage:\n/setprice <premium|vip> <30|90|180|360> <stars>")
        message.stop_propagation()
        return

    plan_type = args[1].lower()
    if plan_type not in ("premium", "vip"):
        await message.reply("Usage:\n/setprice <premium|vip> <30|90|180|360> <stars>")
        message.stop_propagation()
        return

    duration_arg = args[2]
    if duration_arg not in ("30", "90", "180", "360"):
        await message.reply("❌ Package not found.")
        message.stop_propagation()
        return

    stars_arg = args[3]
    if not stars_arg.isdigit() or int(stars_arg) <= 0:
        await message.reply("Usage:\n/setprice <premium|vip> <30|90|180|360> <stars>")
        message.stop_propagation()
        return

    old_price = update_subscription_price(plan_type, int(duration_arg), int(stars_arg))
    if old_price is None:
        await message.reply("❌ Package not found.")
        message.stop_propagation()
        return

    plan_name = "Premium" if plan_type == "premium" else "VIP"
    await message.reply(f"✅ {plan_name} {duration_arg} days updated\nOld price: {old_price} ⭐\nNew price: {int(stars_arg)} ⭐")
    message.stop_propagation()

@Client.on_message(filters.command("check_reports") & filters.user(ADMINS), group=-10)
async def check_reports(client: Client, message: Message):
    reports = await database.get_reports(10)
    if not reports:
        await message.reply("No reports found.")
        return

    text = "**Latest Reports:**\n\n"
    for report in reports:
        reporter = report.get("user_id")
        reported = report.get("target_id")
        reason = report.get("reason")
        
        reporter_link = f"<a href='tg://user?id={reporter}'>{reporter}</a>"
        reported_link = f"<a href='tg://user?id={reported}'>{reported}</a>"
        
        text += f"👮 **From:** {reporter_link}\n👤 **Target:** {reported_link} (`/ban {reported}`)\n📝 **Reason:** {reason}\n{'-'*20}\n"
    
    await message.reply(text)
    message.stop_propagation()

@Client.on_message(filters.command("ban") & filters.user(ADMINS), group=-10)
async def ban(client: Client, message: Message):
    args = message.text.split()
    if len(args) > 1:
        user = int(args[1])
        userdata = await storage.get_user(user)
        user_chat = int(userdata.get('in_chat'))

        if user_chat != 0:
            user_data_in_chat = await storage.get_user(user_chat)
            await asyncio.gather(
                storage.set_user(user_chat, {"status": "standby", "in_chat": 0}),
                storage.set_user(user, {"status": "standby", "in_chat": 0}),
                client.send_message(user_chat, get_message(user_data_in_chat['lang'], "chat.stopped.partner"))
            )
        
        userdata['ban']['totals'] += 1
        unbanbtn = None
        if userdata['ban']['totals'] < 5:
            unbanbtn = InlineKeyboardMarkup([[InlineKeyboardButton(get_message(userdata['lang'], 'unban_btn'), callback_data="buy_unban")]])
        await storage.ban_user(user, userdata)
        await asyncio.gather(
            client.send_message(user, get_message(userdata['lang'], "ban_alert"), reply_markup=unbanbtn),
            message.reply(f"User {user} banned!")
        )
    message.stop_propagation()

@Client.on_message(filters.command("unban") & filters.user(ADMINS), group=-10)
async def unban(client: Client, message: Message):
    args = message.text.split()
    if len(args) > 1:
        user = int(args[1])
        await storage.unban_user(user, True)
        userdata = await storage.get_user(user)
        await asyncio.gather(
            client.send_message(user, get_message(userdata['lang'], "unban_alert")),
            message.reply(f"User {user} unbanned!")
        )
    message.stop_propagation()

@Client.on_message(filters.command("refund") & filters.user(ADMINS), group=-10)
async def refund(client: Client, message: Message):
    args = message.text.split()
    if len(args) == 3:
        user_id = int(args[1])
        tx = args[2]
        await client.refund_star_payment(user_id, tx)
        await message.reply(f"User {user_id} refunded!")
    message.stop_propagation()

@Client.on_message(filters.command(["subp", 'subv']) & filters.user(ADMINS), group=-10)
async def subadd(client: Client, message: Message):
    args = message.text.split()
    if len(args) > 1:
        user = int(args[1])
        expires_at = datetime.now(UTC) + timedelta(days=int(args[2]))
        subscription_data = {
            "active": True,
            "expires_at": expires_at,
            "plan": "premium" if args[0].lower() == "/subp" else "vip"
        }

        if args[0].lower() == "/subv":
            await client.unban_chat_member(GROUP_ID, user)

        await database.update_user(user, {"subscription": subscription_data})
        verify_user = await storage.get_user(user)
        if verify_user:
            subscription_data["expires_at"] = expires_at.isoformat()
            verify_user["subscription"] = subscription_data
            await storage.set_user(user, verify_user)
            
            # Add to expiration queue
            await storage.add_subscription(user, expires_at.timestamp())
        await message.reply(f"User {user} added to premium users!")
    message.stop_propagation()

@Client.on_message(filters.command("subr") & filters.user(ADMINS), group=-10)
async def subremove(client: Client, message: Message):
    args = message.text.split()
    if len(args) > 1:
        user = int(args[1])
        await database.update_user(user, {"subscription.active": False})
        verify_user = await storage.get_user(user)
        if verify_user:
            verify_user["subscription"]["active"] = False
            await storage.set_user(user, verify_user)

            get_user = await client.get_chat_member(GROUP_ID, user)
            if get_user and get_user.status == ChatMemberStatus.MEMBER:
                await client.ban_chat_member(GROUP_ID, user)

            # Remove from expiration queue
            await storage.remove_subscription(user)
        await message.reply(f"User {user} removed from premium users!")
    message.stop_propagation()

@Client.on_message(filters.command('creators') & filters.user(ADMINS), group=-10)
async def creators(client: Client, message: Message):
    text = "**List of Creators:**\n\n"
    for idcr, data in CREATORS.items():
        text += f"`{idcr}` - {data['name']}\n"
    await message.reply(text)
    message.stop_propagation()

@Client.on_message(filters.media_group & filters.incoming & filters.user(ADMINS) & ~filters.channel & ~custom_filters.in_chat(), group=-10)
async def forward(client: Client, message: Message):
    if message.media_group_id in processed_media_groups:
        message.stop_propagation()
        return

    processed_media_groups[message.media_group_id] = datetime.now(UTC).timestamp()
    
    # Cleanup old entries
    for key in list(processed_media_groups.keys()):
        if datetime.now(UTC).timestamp() - processed_media_groups[key] > 60:
            del processed_media_groups[key]

    new_media = await client.copy_media_group(CHANNEL_ID, message.chat.id, message.id)
    msg = new_media[0] if isinstance(new_media, list) else new_media
    await message.reply(f'✅ **Album Saved!**\n\n✍️ Now use this command to set in the creator album: `/setcreatoralbum {msg.chat.id} {msg.id} id_creator`')
    message.stop_propagation()

@Client.on_message(filters.command('setcreatoralbum') & filters.user(ADMINS), group=-10)
async def setcreatoralbum(client: Client, message: Message):
    args = message.text.split()
    if len(args) > 3:
        album_id = int(args[1])
        album_msg_id = int(args[2])
        creator_id = int(args[3])
        CREATORS[creator_id]['album_data'] = [album_id, album_msg_id]
        with open("./creators.json", "w") as f:
            json.dump({'creators': list(CREATORS.values())}, f, indent=3)
        await message.reply(f"Album set for creator {creator_id}!")
    message.stop_propagation()

@Client.on_message(filters.command("send") & filters.user(ADMINS), group=-10)
async def send_broadcast(client: Client, message: Message):
    # Ensure broadcast manager has client
    broadcast_manager.set_client(client)
    
    if broadcast_manager.is_running:
        await message.reply("⚠️ A broadcast is already running! Please wait.")
        message.stop_propagation()
        return

    if not message.reply_to_message and len(message.command) < 2:
        await message.reply("<b>Usage:</b> /send [message] or reply to a message.")
        message.stop_propagation()
        return

    users = await database.get_all_users()
    if not users:
        await message.reply("No users found to broadcast to.")
        message.stop_propagation()
        return

    status_msg = await message.reply(f"🚀 **Starting broadcast to {len(users)} users...**", quote=True)
    
    # Analyze payload
    if message.reply_to_message:
        payload = message.reply_to_message
        mode = "copy"
    else:
        payload = message.text.split(None, 1)[1]
        mode = "send"

    # Start broadcast
    await broadcast_manager.start_broadcast(users, payload, mode)
    
    # Monitor progress with timeout (max 2 hours)
    max_wait_time = 2 * 60 * 60  # 2 hours in seconds
    elapsed_time = 0
    update_interval = 60  # seconds
    last_stats = None
    
    while broadcast_manager.is_running and elapsed_time < max_wait_time:
        await asyncio.sleep(update_interval)
        elapsed_time += update_interval
        stats = broadcast_manager.stats.copy()
        
        # Only edit if stats changed (avoid MessageNotModified)
        if stats != last_stats:
            last_stats = stats
            try:
                await status_msg.edit(
                    f"🚀 **Broadcast In Progress**\n\n"
                    f"✅ Sent: `{stats['sent']}`\n"
                    f"🚫 Blocked/Deleted: `{stats['deleted']}`\n"
                    f"❌ Failed: `{stats['failed']}`\n"
                    f"👥 Total: `{stats['sent']+stats['deleted']+stats['failed']}/{stats['total']}`\n"
                    f"⏱️ Elapsed: `{elapsed_time // 60}m`"
                )
            except MessageNotModified:
                pass  # Stats didn't change visually, ignore
            except Exception:
                pass  # Message may have been deleted
    
    # Check if timed out
    if elapsed_time >= max_wait_time and broadcast_manager.is_running:
        timeout_msg = "\n⚠️ **Monitoring timed out** (broadcast may still be running in background)"
    else:
        timeout_msg = ""
    
    # Final status with error handling
    stats = broadcast_manager.stats
    try:
        await status_msg.edit(
            f"✅ **Broadcast Completed!**{timeout_msg}\n\n"
            f"✅ Sent: `{stats['sent']}`\n"
            f"🚫 Blocked/Deleted: `{stats['deleted']}`\n"
            f"❌ Failed: `{stats['failed']}`\n"
            f"👥 Total Processed: `{stats['total']}`"
        )
    except Exception:
        # If edit fails, try sending a new message
        try:
            await message.reply(
                f"✅ **Broadcast Completed!**{timeout_msg}\n\n"
                f"✅ Sent: `{stats['sent']}`\n"
                f"🚫 Blocked/Deleted: `{stats['deleted']}`\n"
                f"❌ Failed: `{stats['failed']}`\n"
                f"👥 Total Processed: `{stats['total']}`"
            )
        except Exception:
            pass
    
    message.stop_propagation()

@Client.on_message(filters.command("info") & filters.user(ADMINS), group=-10)
async def info(client: Client, message: Message):
    user = message.text.split()
    if len(user) > 1:
        try:
            user_id = int(user[1])
        except ValueError:
            await message.reply("⚠️ Invalid User ID.")
            return

        chat_info = None
        try:
            chat_info = await client.get_chat(user_id)
        except Exception:
            pass
        
        db_user = await storage.get_user(user_id)
        
        if not db_user and not chat_info:
            await message.reply("❌ User not found in Database and Telegram.")
            return
            
        text = f"👤 **User Info for** `{user_id}`\n\n"
        
        # Telegram Data
        if chat_info:
            first = chat_info.first_name or ""
            last = chat_info.last_name or ""
            full_name = (first + " " + last).strip() or "N/A"
            username = f"@{chat_info.username}" if chat_info.username else "N/A"
            dc_id = chat_info.dc_id or "N/A"
            bio = chat_info.bio or "N/A"
            if len(bio) > 20: bio = bio[:20] + "..."
            
            text += f"📱 **Telegram Data**\n"
            text += f"• **Name:** {full_name}\n"
            text += f"• **Username:** {username}\n"
            text += f"• **DC ID:** {dc_id}\n"
            text += f"• **Bio:** {bio}\n"
            text += f"• **Scam:** {'Yes ⚠️' if chat_info.is_scam else 'No'}\n"
            text += f"• **Fake:** {'Yes ⚠️' if chat_info.is_fake else 'No'}\n\n"
        else:
            text += "⚠️ **Telegram Account Not Found** (Deleted/Invalid)\n\n"
            
        # Database Data
        if db_user:
            lang = db_user.get('lang', 'N/A')
            status = db_user.get('status', 'N/A')
            in_chat = db_user.get('in_chat', 0)
            sex = db_user.get('sex', 'N/A')
            
            # Fetch joined_at from MongoDB (not stored in cache)
            joined_at = 'N/A'
            mongo_user = await database.get_user(user_id)
            if mongo_user:
                joined_at = mongo_user.get('joined_at', 'N/A')
            if isinstance(joined_at, datetime):
                joined_at = joined_at.strftime('%d/%m/%Y %H:%M:%S')
            
            # Subscription
            sub_data = db_user.get('subscription', {})
            if isinstance(sub_data, str):
                try:
                    sub_data = json.loads(sub_data)
                except:
                    sub_data = {}
            
            is_sub = sub_data.get('active', False)
            plan = sub_data.get('plan', 'N/A').capitalize() if is_sub else "Free"
            expiry = sub_data.get('expires_at', 'N/A')
            if is_sub and expiry != 'N/A':
                try:
                    expiry_dt = datetime.fromisoformat(expiry)
                    expiry = expiry_dt.strftime("%d/%m/%Y")
                except:
                    pass
            
            # Ban Info
            ban_data = db_user.get('ban', {})
            if isinstance(ban_data, str):
                try:
                    ban_data = json.loads(ban_data)
                except:
                    ban_data = {}
            
            is_banned = ban_data.get('active', False) if isinstance(ban_data, dict) else False
            ban_totals = ban_data.get('totals', 0) if isinstance(ban_data, dict) else 0

            text += f"💽 **Database Data**\n"
            text += f"• **Language:** {str(lang).upper()}\n"
            text += f"• **Sex:** {sex}\n"
            text += f"• **Status:** `{status}`\n"
            text += f"• **In Chat:** `{in_chat}`\n"
            text += f"• **Joined At:** {joined_at}\n"
            text += f"• **Subscription:** {'✅' if is_sub else '❌'} ({plan})\n"
            if is_sub:
                text += f"• **Expires:** {expiry}\n"
            
            text += f"• **Banned:** {'🚫 Yes' if is_banned else '✅ No'}\n"
            text += f"• **Ban Count:** {ban_totals}\n"
        else:
            text += "❌ **User not found in Database**\n"
            
        await message.reply(text)
    else:
        await message.reply("Usage: /info [user_id]")
    message

@Client.on_message(filters.command("inforeport") & filters.user(ADMINS), group=-10)
async def inforeport(client: Client, message: Message):
    args = message.text.split()
    if len(args) > 1:
        user = int(args[1])
        reports = await database.get_report_count(user)
        if not reports:
            await message.reply("No reports found.")
            return
        
        await message.reply(f'Total reports of {user}: {reports}\n\n`/ban {user}`')
    message.stop_propagation()

@Client.on_message(filters.command("reports") & filters.user(ADMINS), group=-10)
async def reports(client: Client, message: Message):
    reports = await database.get_duplicate_reports()
    if not reports:
        await message.reply("No reports found.")
        return
    
    text = "**Users:**\n\n"
    c = 0
    for user in reports:
        if c == 20: break
        text += f"User `{user['_id']}` has {user['count']} reports.\n"
        c += 1
    await message.reply(text)
    message.stop_propagation()

@Client.on_message(filters.command("chgender") & filters.user(ADMINS), group=-10)
async def chgender(client: Client, message: Message):
    args = message.text.split()
    if len(args) > 1:
        user = int(args[1])
        userdata = (await storage.get_user(user)).get('sex')
        await asyncio.gather(
            storage.set_user(user, {"sex": "M" if userdata == "F" else "F"}),
            database.update_user(user, {"sex": "M" if userdata == "F" else "F"})
        )
        await message.reply(f"Gender of user {user} changed to {'M' if userdata == 'F' else 'F'}")
    message.stop_propagation()

@Client.on_message(filters.command('starbal') & filters.user(ADMINS), group=-10)
async def get_star_bal(client: Client, message: Message):
    star_balance = await client.get_stars_balance()
    stars = star_balance.stars if hasattr(star_balance, 'stars') else star_balance
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get('https://api.frankfurter.dev/v2/rate/USD/EUR') as response:
                if response.status == 200:
                    json_resp = await response.json()
                    if json_resp and 'rate' in json_resp:
                        rate = json_resp['rate']
                        eur_amount = round(stars * 0.013 * rate, 2)
                        await message.reply(f"⭐️ **Star Balance:** {stars}\n💶 **EUR:** €{eur_amount}")
                    else:
                        await message.reply(f"⭐️ **Star Balance:** {stars}\n⚠️ Could not fetch exchange rate.")
                else:
                    await message.reply(f"⭐️ **Star Balance:** {stars}\n⚠️ Exchange rate API error.")
        except Exception as e:
            await message.reply(f"⭐️ **Star Balance:** {stars}\n⚠️ Error: {e}")

@Client.on_message(filters.command('totalusers') & filters.user(ADMINS), group=-10)
async def total_users(client: Client, message: Message):
    total = await database.count_users()
    await message.reply(f"👥 **Totale utenti registrati:** {total}")
    message.stop_propagation()

@Client.on_message(filters.command('readfeed') & filters.user(ADMINS), group=-10)
async def read_feedback(client: Client, message: Message):
    text, markup = await _build_feedback_page(0)
    await message.reply(text, reply_markup=markup)
    message.stop_propagation()

@Client.on_callback_query(filters.regex(r"^readfeed:") & filters.user(ADMINS))
async def readfeed_paginate(client: Client, callback_query):
    data = callback_query.data
    if data == "readfeed:noop":
        await callback_query.answer()
        return

    page = int(data.split(":")[1])
    text, markup = await _build_feedback_page(page)

    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except MessageNotModified:
        pass
    await callback_query.answer()