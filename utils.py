import asyncio
import logging
from pymongo import AsyncMongoClient
from bson import ObjectId
import valkey.asyncio as valkey
from pyrogram import filters
from pyrogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery

import json
import os
import time
from datetime import datetime
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid, FileReferenceExpired
# CONSTANTS
ADMINS = []
PAYLOAD_USER = {
    'lang': '',
    'sex': '',
    'adult': 0,
    'allowforward': 0,
    'hidecontent': 0,
    'status': 'standby',
    'in_chat': 0,
    'subscription': '{}',
    'ban': 0,
    'captcha': 0,
    'refId': '',
    'active': 0
}
MATCHMAKING_SCRIPT = """
local queue_key = KEYS[1]
local is_premium = (KEYS[2] == 1)
local user_id = ARGV[1]
local from_sex = ARGV[2]
local to_sex = ARGV[3]

redis.call("SREM", queue_key, user_id)

local partner_id = false

if is_premium then
    partner_id = redis.call("SPOP", "queue:"..to_sex..":"..from_sex)
    if not partner_id then
        partner_id = redis.call("SPOP", "queue:"..to_sex..":A")
    end
else
    -- For non-premium: search based on to_sex preference
    if to_sex == "A" then
        -- Random match: try opposite sex first, then same sex
        local opposite_sex = "F"
        if from_sex == "F" then opposite_sex = "M" end
        
        -- Try opposite sex looking for our sex
        partner_id = redis.call("SPOP", "queue:"..opposite_sex..":"..from_sex)
        if not partner_id then
            -- Try opposite sex looking for anyone
            partner_id = redis.call("SPOP", "queue:"..opposite_sex..":A")
        end
        if not partner_id then
            -- Try same sex looking for our sex
            partner_id = redis.call("SPOP", "queue:"..from_sex..":"..from_sex)
        end
        if not partner_id then
            -- Try same sex looking for anyone
            partner_id = redis.call("SPOP", "queue:"..from_sex..":A")
        end
    else
        -- Specific sex requested
        partner_id = redis.call("SPOP", "queue:"..to_sex..":"..from_sex)
        if not partner_id then
            partner_id = redis.call("SPOP", "queue:"..to_sex..":A")
        end
    end
end

if partner_id then
    redis.call("HSET", "userdata:"..user_id, "in_chat", partner_id)
    redis.call("HSET", "userdata:"..partner_id, "in_chat", user_id)
    return {"MATCH", partner_id}
else
    redis.call("SADD", queue_key, user_id)
    return {"WAITING", false}
end
"""

TTL_USERDATA = 60*60
SUPPORT = os.getenv("SUPPORT")
GROUP_ID = int(os.getenv("GROUP_ID"))
INVITE_LINK = os.getenv("INVITE_LINK")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
FB_ACCESS = os.getenv("FB_ACCESS")
PIXEL_ID = os.getenv("PIXEL_ID")
LANGUAGES_CACHE = {}
SUBSCRIPTIONS = json.load(open("./subscriptions.json", "r", encoding="utf-8"))
CREATORS = {}
with open("./creators.json", "r", encoding="utf-8") as f:
    data = json.load(f)
    id_cr = 1
    if data.get("creators"):
        for creator in data['creators']:
            CREATORS[id_cr] = creator
            id_cr += 1

# FUNCTIONS
def get_language_data(language: str) -> dict:
    if language in LANGUAGES_CACHE:
        return LANGUAGES_CACHE[language]
    
    try:
        with open(f"languages/{language}.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            LANGUAGES_CACHE[language] = data
            return data
    except Exception:
        return {}
def get_message(language: str, key: str) -> str:
    data = get_language_data(language)
    if not data:
        return key

    try:
        keys = key.split(".")
        for k in keys:
            data = data[k]
            
        return data
    except Exception:
        return key
def get_available_languages(reset: bool = False) -> list[dict]:
    global SUBSCRIPTIONS, CREATORS
    if reset:
        LANGUAGES_CACHE.clear()
        with open("./subscriptions.json", "r", encoding="utf-8") as f:
            new_data = json.load(f)
            SUBSCRIPTIONS.clear()
            SUBSCRIPTIONS.update(new_data)
        with open("./creators.json", "r", encoding="utf-8") as f:
            new_data = json.load(f)
            CREATORS.clear()
            id_cr = 1
            if new_data.get("creators"):
                for creator in new_data['creators']:
                    CREATORS[id_cr] = creator
                    id_cr += 1

    languages = []
    if not os.path.exists("./languages"):
        return languages

    for file in os.listdir("./languages"):
        if file.endswith(".json"):
            code = file.split(".")[0]
            data = get_language_data(code)
            if data:
                name = data.get("language_name", code)
                languages.append({"code": code, "name": name})
    return languages
def convert_types(data: dict):
    for k, v in data.items():
        if v in ['0', '1']:
            data[k] = int(v)
        if isinstance(v, str) and len(v) > 10:
            try:
                data[k] = json.loads(v)
            except:
                pass
    return data

def normalize_expires_at(expires_at):
    """Return a backward-compatible string representation for expires_at."""
    if isinstance(expires_at, datetime):
        return expires_at.isoformat()
    if isinstance(expires_at, str) or expires_at is None:
        return expires_at
    return str(expires_at)

def normalize_subscription(subscription):
    """Normalize subscription payloads for Redis/Mongo round-tripping."""
    if not isinstance(subscription, dict):
        return subscription

    normalized = subscription.copy()
    if "expires_at" in normalized:
        normalized["expires_at"] = normalize_expires_at(normalized.get("expires_at"))
    return normalized

def serialize_redis_value(value):
    if isinstance(value, dict):
        return json.dumps({k: serialize_redis_value(v) if isinstance(v, dict) else normalize_expires_at(v) for k, v in value.items()})
    if isinstance(value, datetime):
        return value.isoformat()
    return value
def load_admins():
    ADMINS.clear()
    ADMINS.extend(list(map(int, os.getenv("ADMIN_ID").split(","))))

def update_subscription_price(plan_type: str, duration: int, stars: int):
    global SUBSCRIPTIONS

    plan_type = plan_type.lower()
    if plan_type not in ("premium", "vip"):
        return None

    packages = SUBSCRIPTIONS.get(plan_type, {}).get("packages", [])
    package = next((p for p in packages if p.get("duration") == duration), None)
    if not package:
        return None

    old_price = package["price"][0]
    package["price"][0] = stars

    with open("./subscriptions.json", "w", encoding="utf-8") as f:
        json.dump(SUBSCRIPTIONS, f, indent=3)

    with open("./subscriptions.json", "r", encoding="utf-8") as f:
        new_data = json.load(f)
        SUBSCRIPTIONS.clear()
        SUBSCRIPTIONS.update(new_data)

    return old_price

def get_commands(lang):
    data = get_language_data(lang)
    commands = data.get('commands')
    # Fallback to English if commands not found in specified language
    if not commands:
        data = get_language_data('en')
        commands = data.get('commands', {})
    rows = []
    for cmd, desc in commands.items():
        rows.append(BotCommand(cmd, desc))
    return rows

# CLASSES
class Database:
    def __init__(self):
        self.client = None
        self.db = None
    
    async def connect(self):
        self.client = AsyncMongoClient(os.getenv("URI_DB"), tz_aware=True)
        self.db = self.client.get_default_database()
        await self.ensure_feedback_index()

    async def close(self):
        if self.client:
            await self.client.close()

    # OTHER METHODS
    async def get_user(self, user_id: int):
        if self.db is not None:
            return await self.db.users.find_one({"user_id": user_id})

    async def add_user(self, user_id: int, data: dict):
        if self.db is not None:
            return await self.db.users.insert_one({"user_id": user_id, **data})
    
    async def update_user(self, user_id: int, data: dict):
        if self.db is not None:
            return await self.db.users.update_one({"user_id": user_id}, {"$set": data})

    async def report_user(self, user_id: int, target_id: int, reason: str):
        if self.db is not None:
            return await self.db.reports.insert_one({"user_id": user_id, "target_id": target_id, "reason": reason})

    async def get_reports(self, limit: int = 10):
        if self.db is not None:
            cursor = self.db.reports.find().sort("_id", -1).limit(limit)
            return await cursor.to_list(length=limit)

    async def get_all_users(self):
        if self.db is not None:
            cursor = self.db.users.find({"active": {"$ne": False}}, {"user_id": 1})
            return await cursor.to_list(length=None)
        return []

    async def count_users(self):
        if self.db is not None:
            return await self.db.users.count_documents({})
        return 0
    async def get_report_count(self, user_id: int):
        if self.db is not None:
            tot_counts = await self.db.reports.count_documents({"target_id": user_id})
            return tot_counts
        return 0
    async def get_duplicate_reports(self):
        if self.db is not None:
            result = await self.db.reports.aggregate([
                {
                    "$group": {
                        "_id": "$target_id",
                        "count": {"$sum": 1}
                    }
                },
                {
                    "$match": {"count": {"$gt": 3}}
                },
                {"$sort": {"count": -1}}
            ])
            return await result.to_list()
        return []

    async def delete_reports(self, user_id: int):
        if self.db is not None:
            await self.db.reports.delete_many({
                "$or": [
                    {"target_id": user_id},
                    {"user_id": user_id}
                ]
            })
    
    async def get_ads_info(self, id_ads: str) -> dict:
        if self.db is not None:
            return await self.db.ads.find_one({"_id": ObjectId(id_ads)})

    # FEEDBACK METHODS
    async def ensure_feedback_index(self):
        """Create a unique index on user_id in the feedback collection."""
        if self.db is not None:
            try:
                await self.db.feedback.create_index("user_id", unique=True)
            except Exception as e:
                logging.error(f"Failed to create feedback index: {e}")

    async def get_feedback(self, user_id: int) -> dict:
        """Get existing feedback for a user, or None if not found."""
        if self.db is not None:
            return await self.db.feedback.find_one({"user_id": user_id})
        return None

    async def get_feedback_page(self, page: int, per_page: int = 10) -> tuple:
        """Get a page of feedback documents sorted by newest first.
        Returns (items_list, total_count)."""
        if self.db is None:
            return [], 0
        total = await self.db.feedback.count_documents({})
        cursor = self.db.feedback.find().sort("timestamp", -1).skip(page * per_page).limit(per_page)
        items = await cursor.to_list(length=per_page)
        return items, total


    async def bulk_insert_feedback(self, items: list) -> dict:
        """Bulk insert pending feedback items. Returns {inserted, total}."""
        if not items or self.db is None:
            return {"inserted": 0, "total": len(items) if items else 0}

        documents = [{
            "user_id": item["user_id"],
            "feedback_content": item["feedback_content"],
            "timestamp": datetime.fromtimestamp(item["timestamp"]),
            "status": "submitted"
        } for item in items]

        try:
            result = await self.db.feedback.insert_many(documents, ordered=False)
            return {"inserted": len(result.inserted_ids), "total": len(documents)}
        except Exception as e:
            # BulkWriteError with duplicate keys is expected; ordered=False inserts what it can
            inserted = 0
            if hasattr(e, 'details') and isinstance(e.details, dict):
                inserted = e.details.get('nInserted', 0)
            logging.warning(f"Bulk feedback insert: {inserted}/{len(documents)} inserted, duplicates skipped")
            return {"inserted": inserted, "total": len(documents)}

class Storage:

    def __init__(self):
        self.client = valkey.Valkey(decode_responses=True)
        self.matchmaking_sha = None
        self.last_refresh = {}
    
    async def close(self):
        if self.client:
            await self.client.aclose()

    async def get_user(self, user_id: int):
        userdata = await self.client.hgetall(f'userdata:{user_id}')
        
        if userdata:
            # Verifica che tutte le chiavi essenziali siano presenti
            required_keys = {'lang', 'sex', 'subscription', 'adult', 'allowforward', 'hidecontent', 'ban', 'refId', 'active'}
            existing_keys = set(userdata.keys())
            missing_keys = required_keys - existing_keys
            
            if missing_keys:
                # Chiavi mancanti: recupera dal database e ricostruisci
                db_user = await database.get_user(user_id)
                if db_user:
                    full_userdata = PAYLOAD_USER.copy()
                    for k, v in db_user.items():
                        if k in PAYLOAD_USER:
                            if isinstance(v, bool):
                                full_userdata[k] = int(v)
                            elif isinstance(v, dict):
                                if k == 'subscription':
                                    v = normalize_subscription(v)
                                full_userdata[k] = json.dumps(v, default=normalize_expires_at)
                            else:
                                full_userdata[k] = v
                    
                    # Mantieni i valori correnti di in_chat e status (potrebbero essere aggiornati)
                    if 'in_chat' in userdata:
                        full_userdata['in_chat'] = userdata['in_chat']
                    if 'status' in userdata:
                        full_userdata['status'] = userdata['status']
                    if 'last_partner' in userdata:
                        full_userdata['last_partner'] = userdata['last_partner']
                    
                    await self.set_user(user_id, full_userdata)
                    return convert_types(full_userdata)
            
            return convert_types(userdata)

        db_user = await database.get_user(user_id)
        if db_user:
            userdata = PAYLOAD_USER.copy()
            for k, v in db_user.items():
                if k in PAYLOAD_USER:
                    if isinstance(v, bool):
                        userdata[k] = int(v)
                    elif isinstance(v, dict):
                        if k == 'subscription':
                            v = normalize_subscription(v)
                        userdata[k] = json.dumps(v, default=normalize_expires_at)
                    else:
                        userdata[k] = v
            
            await self.set_user(user_id, userdata)
            return convert_types(userdata)
        else: 
            return None
    
    async def set_user(self, user_id: int, data: dict, with_delete=False, chat=False):
        # Prepare data for Redis (serialize dicts)
        redis_data = data.copy()
        for k, v in redis_data.items():
            if isinstance(v, dict):
                if k == "subscription":
                    v = normalize_subscription(v)
                redis_data[k] = json.dumps(v, default=normalize_expires_at)
            elif isinstance(v, datetime):
                redis_data[k] = v.isoformat()

        async with self.client.pipeline() as pipe:
            if with_delete:
                pipe.delete(f'userdata:{user_id}')
            pipe.hset(f'userdata:{user_id}', mapping=redis_data)

            if not chat: pipe.expire(f'userdata:{user_id}', TTL_USERDATA)
            else: pipe.persist(f'userdata:{user_id}')

            await pipe.execute()
            return True
    
    async def update_adult(self, user_id: int):
        await database.update_user(user_id, {'adult': True})
        async with self.client.pipeline() as pipe:
            pipe.hset(f'userdata:{user_id}', mapping={"adult": 1})
            pipe.expire(f'userdata:{user_id}', TTL_USERDATA)
            await pipe.execute()
            return True
    
    async def search_partner(self, queue_key: str, user_id: int, sex: str, to_sex: str, premium: bool = False):
        if self.matchmaking_sha is None:
            self.matchmaking_sha = await self.client.script_load(MATCHMAKING_SCRIPT)
        
        try:
            result = await self.client.evalsha(self.matchmaking_sha, 2, queue_key, int(premium), user_id, sex, to_sex)
        except Exception:
            self.matchmaking_sha = await self.client.script_load(MATCHMAKING_SCRIPT)
            result = await self.client.evalsha(self.matchmaking_sha, 2, queue_key, int(premium), user_id, sex, to_sex)
            
        return result

    async def leave_queue(self, user_id: int, sex: str):
        """Remove user from all possible matchmaking queues"""
        queues = [
            f"queue:{sex}:A",
            f"queue:{sex}:M",
            f"queue:{sex}:F"
        ]
        async with self.client.pipeline() as pipe:
            for q in queues:
                pipe.srem(q, user_id)
            await pipe.execute()

    async def status_subscription(self, user_id: int):
        user = await self.get_user(user_id)
        return user.get('subscription', {}).get('active', False)

    async def add_subscription(self, user_id: int, expires_at: float):
        """Add user to subscription expiration queue"""
        await self.client.zadd("subscriptions:expiration", {str(user_id): expires_at})

    async def get_expired_subscriptions(self) -> list:
        """Get list of expired user_ids"""
        now = time.time()
        return await self.client.zrangebyscore("subscriptions:expiration", "-inf", now)

    async def remove_subscription(self, user_id: int):
        """Remove user from subscription expiration queue"""
        await self.client.zrem("subscriptions:expiration", str(user_id))

    async def ban_user(self, user_id: int, userdata):
        user = userdata
        if user:
            ban_info = user['ban']
            if not ban_info:
                logging.error(f"User {user_id} not found in database to ban it")
                return
            else:
                ban_info['active'] = True
                user['ban'] = json.dumps(ban_info)
                await database.update_user(user_id, {'ban': ban_info})
                await database.delete_reports(user_id)
            await self.set_user(user_id, user)

    async def unban_user(self, user_id: int, reset_total=False):
        user = await self.get_user(user_id)
        if user:
            ban_info = user['ban']
            if not ban_info:
                logging.error(f"User {user_id} not found in database to unban it")
                return
            else:
                ban_info['active'] = False
                if reset_total:
                    ban_info['totals'] = 0
                user['ban'] = ban_info
                await database.update_user(user_id, {'ban': ban_info})
            await self.set_user(user_id, user)

    # FEEDBACK QUEUE METHODS (memory-first, batch-flushed to DB)
    async def has_submitted_feedback(self, user_id: int) -> bool:
        """Check if user already submitted feedback (Redis set + MongoDB fallback)."""
        if await self.client.sismember("feedback:done", user_id):
            return True
        # Fallback to MongoDB for persistence across restarts
        existing = await database.get_feedback(user_id)
        if existing:
            await self.client.sadd("feedback:done", user_id)
            return True
        return False

    async def queue_feedback(self, user_id: int, feedback_content: str) -> bool:
        """Queue feedback in Redis for batch processing. Returns False if duplicate."""
        if await self.has_submitted_feedback(user_id):
            return False

        entry = json.dumps({
            "user_id": user_id,
            "feedback_content": feedback_content,
            "timestamp": time.time()
        })
        await self.client.rpush("feedback:pending", entry)
        await self.client.sadd("feedback:done", user_id)
        return True

    async def get_pending_feedback(self) -> tuple:
        """Read all pending feedback items without removing them from Redis.
        Returns (items_list, count) where count is used for clear_pending_feedback."""
        raw = await self.client.lrange("feedback:pending", 0, -1)
        return [json.loads(entry) for entry in raw], len(raw)

    async def clear_pending_feedback(self, count: int):
        """Remove the first `count` items from the pending queue after successful flush."""
        if count > 0:
            await self.client.ltrim("feedback:pending", count, -1)


    async def refresh_chat_session(self, user_id: int, partner_id: int = 0):
        now = time.time()
        # Throttling to avoid spamming Redis: only refresh every 5 minutes (300s)
        if now - self.last_refresh.get(user_id, 0) < 300:
            return

        self.last_refresh[user_id] = now
        if partner_id:
            self.last_refresh[partner_id] = now

        async with self.client.pipeline() as pipe:
            pipe.expire(f'userdata:{user_id}', TTL_USERDATA)
            if partner_id:
                pipe.expire(f'userdata:{partner_id}', TTL_USERDATA)
            await pipe.execute()

class ChatQueue:
    def __init__(self):
        self.queues = {}
        self.processing = {}

    async def add_message(self, chat_id: int, message: dict):
        if chat_id not in self.queues:
            self.queues[chat_id] = asyncio.Queue()
            # Start processing loop for this chat if not already running
            if chat_id not in self.processing or self.processing[chat_id].done():
                self.processing[chat_id] = asyncio.create_task(self.process_queue(chat_id))
        
        await self.queues[chat_id].put(message)

    async def process_queue(self, chat_id: int):
        queue = self.queues[chat_id]
        try:
            while True:
                message_data = await queue.get()
                #client = message_data['client']
                message: Message = message_data['message']
                allowforward = message_data['allowforward']
                hidecontent = message_data['hidecontent']
                
                # Simulate "typing" or natural delay
                delay = 0.2
                await asyncio.sleep(delay)
                
                try:
                    if message.photo or message.video:
                        user_data = await storage.get_user(message.from_user.id)
                        subscription = user_data.get('subscription') if user_data else {}
                        if isinstance(subscription, dict) and subscription.get('active'):
                            await message.copy(chat_id, reply_to_message_id=message.reply_to_message_id, protect_content=allowforward, has_spoiler=hidecontent)
                        else:
                            await message.reply(get_message(user_data.get('lang'), "subscription.sub_required"))
                    elif message.sticker or message.animation:
                        user_data = await storage.get_user(message.from_user.id)
                        subscription = user_data.get('subscription') if user_data else {}
                        if isinstance(subscription, dict) and subscription.get('active'):
                            await message.copy(chat_id, reply_to_message_id=message.reply_to_message_id, protect_content=allowforward)
                        else:
                            await message.reply(get_message(user_data.get('lang'), "subscription.sub_required_sticker"))
                    else:
                        await message.copy(chat_id, reply_to_message_id=message.reply_to_message_id, protect_content=allowforward)
                except ValueError as e:
                    if "Unknown media type" in str(e):
                        pass
                    else:
                        raise e
                except FileReferenceExpired:
                    # File reference expired, notify user that media cannot be sent
                    try:
                        user_data = await storage.get_user(message.from_user.id)
                        user_lang = user_data.get('lang', 'en') if user_data else 'en'
                        await message.reply(get_message(user_lang, "chat.media_expired"))
                    except Exception:
                        pass
                except (UserIsBlocked, PeerIdInvalid, InputUserDeactivated):
                     pass
                except Exception as e:
                    import traceback
                    logging.error(f"Error forwarding message to {chat_id}: {e}\n{traceback.format_exc()}")
                
                queue.task_done()
                
                # Rate limiting: ensure at least 1 second between messages
                await asyncio.sleep(1.0)
                
                # Cleanup if empty
                if queue.empty():
                    del self.queues[chat_id]
                    del self.processing[chat_id]
                    break
        except Exception as e:
            logging.error(f"Queue processing error for {chat_id}: {e}")
class CustomFilters:
    def in_registration(self):
        async def func(_, __, message: Message):
            if message.from_user is None:
                return False
            user = await storage.get_user(message.from_user.id)
            if user is None:
                return False
            return bool(user.get("phase"))
        return filters.create(func)

    def is_adult(self):
        async def func(_, __, message: Message):
            if message.from_user is None:
                return False
            user = await storage.get_user(message.from_user.id)
            if user:
                if not user.get("adult"):
                    userlang = user.get("lang") or "en"
                    await message.reply(get_message(userlang, "sexchat.warning"), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_message(userlang, "sexchat.accept"), callback_data="accept")]]), disable_web_page_preview=True)
                    return False
                return True
        return filters.create(func)
    def status(self, value: str):
        async def func(flt, __, message: Message):
            if message.from_user is None or message.from_user.is_bot:
                return False
            
            if isinstance(message, CallbackQuery):
                try:
                    await message.answer()
                except Exception:
                    pass
                
            user = await storage.get_user(message.from_user.id)
            if user is None:
                return False
            return user.get("status") == flt.value
        return filters.create(func, value=value)    
    def in_chat(self):
        async def func(_, __, message: Message):
            if message.from_user is None:
                return False
            user = await storage.get_user(message.from_user.id)
            if user is None:
                return False
            return user.get("in_chat") != 0
        return filters.create(func)

    def is_premium(self, warn_message=False, is_vip=False):
        async def func(flt, __, message):
            if message.from_user is None:
                return False
            user = await storage.get_user(message.from_user.id)
            if not user:
                return False
            if isinstance(message, CallbackQuery):
                message = message.message
            if message is None or message.chat is None:
                return False
            lang = user.get("lang") or "en"
            check_sub = user.get("subscription", {}).get("active")
            if not check_sub:
                if flt.warn_message:
                    try:
                        await message.reply(get_message(lang, "subscription.sub_required"), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_message(lang, "subscription.btn_buy" if not flt.is_vip else "subscription.btn_buy_vip"), callback_data=f"{'premium' if not flt.is_vip else 'vip'}_buy")]]))
                    except Exception:
                        pass
                return False

            if not flt.is_vip:
                return True
            else:
                is_user_vip = user.get("subscription", {}).get("plan") == "vip"
                if flt.warn_message and not is_user_vip:
                    try:
                        await message.reply(get_message(lang, "subscription.upgrade_to_vip"), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_message(lang, "subscription.btn_buy_vip"), callback_data="vip_buy")]]))
                    except Exception:
                        pass
                return is_user_vip
        return filters.create(func, warn_message=warn_message, is_vip=is_vip)

class BroadcastManager:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.client = None
        self.is_running = False
        self.stats = {"sent": 0, "failed": 0, "deleted": 0, "total": 0}
    
    def set_client(self, client):
        self.client = client

    async def start_broadcast(self, users: list, message: Message, mode: str):
        if self.is_running:
             return False
        
        # Reset stats
        self.stats = {"sent": 0, "failed": 0, "deleted": 0, "total": len(users)}
        self.is_running = True  # Set BEFORE creating task to avoid race condition
        
        # Populate queue
        for user in users:
            await self.queue.put((user['user_id'], message, mode))
            
        asyncio.create_task(self.process_queue())
        return True

    async def process_queue(self):
        while not self.queue.empty():
            # Process batch of up to 30 messages (approx 30 msgs/sec target)
            batch = []
            for _ in range(30):
                if self.queue.empty(): break
                batch.append(await self.queue.get())
            
            if not batch: break
            
            start_ts = time.time()
            
            tasks = [self.send_message(user_id, msg, mode) for user_id, msg, mode in batch]
            await asyncio.gather(*tasks)
            
            # Rate limiting: wait remainder of 1 second
            elapsed = time.time() - start_ts
            if elapsed < 1.0:
                await asyncio.sleep(1.0 - elapsed)
        
        self.is_running = False

    async def send_message(self, user_id, message, mode):
        try:
            if mode == "copy":
                await message.copy(user_id)
            else:
                await self.client.send_message(user_id, message)
            self.stats["sent"] += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                if mode == "copy":
                    await message.copy(user_id)
                else:
                    await self.client.send_message(user_id, message)
                self.stats["sent"] += 1
            except Exception:
                self.stats["failed"] += 1
        except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid):
            self.stats["deleted"] += 1
            await database.update_user(user_id, {"active": False}) 
        except Exception as e:
            self.stats["failed"] += 1
            logging.error(f"Broadcast error for {user_id}: {e}")

database = Database()
storage = Storage()

import sys
if "main.py" in sys.argv[0]:
    broadcast_manager = BroadcastManager()
    custom_filters = CustomFilters()
    chat_queue = ChatQueue()
    payments = None
else:
    custom_filters = None
    chat_queue = None
    payments = None
    broadcast_manager = None

