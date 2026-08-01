from pyrogram import Client, idle, utils
from dotenv import load_dotenv

load_dotenv()

from utils import database, storage, load_admins

import os, uvloop
import asyncio
import logging
import tasks
from typing import Optional, Union
from datetime import datetime, timedelta

# FORK FUNCTIONS
def datetime_to_timestamp(dt: Optional[Union[datetime, timedelta]]) -> Optional[int]:
    if isinstance(dt, timedelta):
        return int((datetime.now() + dt).timestamp())
    elif isinstance(dt, datetime):
        return int(dt.timestamp())
    return dt

utils.datetime_to_timestamp = datetime_to_timestamp


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
load_admins()

api_id = os.getenv("API_ID")
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

async def main():

    bot = Client(
        "sexlybot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        plugins=dict(root="plugins")
    )

    await database.connect()
    logging.info("Bot started")
    await bot.start()
    asyncio.create_task(tasks.check_subscriptions(bot))
    asyncio.create_task(tasks.flush_feedback())

    await idle()

    logging.info("Bot stopped")
    await database.close()
    await storage.close()
    await bot.stop()
    return

if __name__ == "__main__":
    uvloop.run(main())
