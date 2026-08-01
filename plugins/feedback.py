import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

from utils import get_message, storage

MAX_FEEDBACK_LENGTH = 200
FEEDBACK_PENDING_TTL = 60  # 1 minute for user to respond
_REDIS_TTL_BUFFER = 5  # Extra seconds on Redis key to let the asyncio task check before expiry


async def _send_feedback_timeout(client: Client, user_id: int, lang: str):
    """Background task: wait for the feedback window to expire, then notify the user."""
    await asyncio.sleep(FEEDBACK_PENDING_TTL)
    # If key still exists, the user didn't submit in time
    deleted = await storage.client.delete(f"feedback_pending:{user_id}")
    if deleted:
        try:
            await client.send_message(user_id, get_message(lang, "feedback.timeout"))
        except Exception as e:
            logging.warning(f"Failed to send feedback timeout to {user_id}: {e}")


@Client.on_message(filters.command("feedback") & filters.private)
async def feedback_start(client: Client, message: Message):
    user_id = message.from_user.id

    # Check if user is registered
    user = await storage.get_user(user_id)
    if not user:
        return

    lang = user.get("lang", "en")

    # Check if user already submitted feedback (Redis + MongoDB fallback)
    try:
        submitted = await storage.has_submitted_feedback(user_id)
    except Exception as e:
        logging.error(f"Error checking feedback status for user {user_id}: {e}")
        await message.reply(get_message(lang, "feedback.error"))
        return

    if submitted:
        await message.reply(get_message(lang, "feedback.already_submitted"))
        return

    # Check if feedback is already pending (user didn't finish previous attempt)
    already_pending = await storage.client.exists(f"feedback_pending:{user_id}")
    if already_pending:
        await message.reply(get_message(lang, "feedback.prompt"))
        return

    # Mark user as waiting for feedback and prompt
    await storage.client.setex(f"feedback_pending:{user_id}", FEEDBACK_PENDING_TTL + _REDIS_TTL_BUFFER, "1")
    await message.reply(get_message(lang, "feedback.prompt"))

    # Schedule timeout notification
    asyncio.create_task(_send_feedback_timeout(client, user_id, lang))


@Client.on_message(filters.text & filters.private & ~filters.regex(r'^/'), group=-2)
async def feedback_handler(client: Client, message: Message):
    """Process text replies from users who are in feedback mode."""
    user_id = message.from_user.id

    # Check if we're waiting for feedback from this user
    try:
        pending = await storage.client.get(f"feedback_pending:{user_id}")
    except Exception:
        return  # Redis error, let other handlers process this message
    if not pending:
        return  # Not in feedback mode, let other handlers process this message

    # Clear the pending flag immediately to prevent re-entry
    await storage.client.delete(f"feedback_pending:{user_id}")

    user = await storage.get_user(user_id)
    if not user:
        return

    lang = user.get("lang", "en")
    feedback_text = message.text.strip()

    if not feedback_text:
        await message.reply(get_message(lang, "feedback.error"))
        message.stop_propagation()
        return

    # Validate character count
    if len(feedback_text) > MAX_FEEDBACK_LENGTH:
        await message.reply(
            get_message(lang, "feedback.too_long").format(count=len(feedback_text))
        )
        message.stop_propagation()
        return

    # Queue in Redis (memory-first, bulk-flushed to MongoDB every 5 minutes)
    try:
        queued = await storage.queue_feedback(user_id, feedback_text)
    except Exception as e:
        logging.error(f"Error queueing feedback for user {user_id}: {e}")
        await message.reply(get_message(lang, "feedback.error"))
        message.stop_propagation()
        return

    if queued:
        await message.reply(get_message(lang, "feedback.success"))
    else:
        await message.reply(get_message(lang, "feedback.already_submitted"))

    message.stop_propagation()
