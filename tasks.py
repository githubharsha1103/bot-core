import asyncio
import logging
from utils import storage, database, get_message, GROUP_ID
from pyrogram.enums import ChatMemberStatus
from pyrogram import Client
from pyrogram.errors import UserNotParticipant, InputUserDeactivated, UserIsBlocked

async def check_subscriptions(client: Client):
    logging.info("Starting subscription check task")
    while True:
        try:
            expired_users = await storage.get_expired_subscriptions()
            if expired_users:
                logging.info(f"Found {len(expired_users)} expired subscriptions")
                
            for user_id in expired_users:
                user_id = int(user_id)
                
                # Get user data first to know language
                user_data = await storage.get_user(user_id)
                
                # Update DB
                await database.update_user(user_id, {"subscription.active": False})
                
                # Update Cache
                if user_data:
                    if 'subscription' in user_data:
                         user_data['subscription']['active'] = False
                         await storage.set_user(user_id, user_data)
                
                # Remove from ZSET
                await storage.remove_subscription(user_id)

                # Remove from group
                try:
                    get_user = await client.get_chat_member(GROUP_ID, user_id)
                    if get_user and get_user.status == ChatMemberStatus.MEMBER:
                        await client.ban_chat_member(GROUP_ID, user_id)
                except UserNotParticipant:
                    logging.debug(f"User {user_id} already left the group")
                except Exception as e:
                    logging.error(f"Failed to remove user {user_id} from group: {e}")
                
                # Notify user
                try:
                    lang = user_data.get('lang') if user_data else 'en'
                    await client.send_message(user_id, get_message(lang, "subscription.expired"))
                except (InputUserDeactivated, UserIsBlocked) as e:
                    logging.debug(f"Cannot notify user {user_id}: {e}")
                except Exception as e:
                    logging.error(f"Failed to notify user {user_id} of expiration: {e}")
                    
        except Exception as e:
            logging.error(f"Error in subscription check: {e}")
        
        await asyncio.sleep(60)


async def flush_feedback():
    """Flush pending feedback from Redis to MongoDB every 5 minutes."""
    logging.info("Starting feedback flush task (interval: 5 minutes)")
    while True:
        await asyncio.sleep(300)  # 5 minutes
        try:
            pending, count = await storage.get_pending_feedback()
            if pending:
                result = await database.bulk_insert_feedback(pending)
                await storage.clear_pending_feedback(count)
                logging.info(f"Feedback flush: {result['inserted']}/{result['total']} entries persisted")
        except Exception as e:
            logging.error(f"Feedback flush error: {e}")
